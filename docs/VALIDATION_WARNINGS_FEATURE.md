# Validation Warnings System

**Date**: 2025-10-16
**Status**: Implemented and Tested

## Overview

The validation warnings system replaces the previous approach of creating fake "balancing" line items when OCR detects discrepancies. Instead of trying to mathematically infer missing items, the system now flags issues for human review with visual context.

## Problem Statement

**Old Approach**: When line items didn't sum to the receipt subtotal (e.g., faded or missing items on receipt), the system would create a fake placeholder line like "$13.23 faded items" to make the totals balance.

**User Feedback**: "Shouldn't we just be flagging the spots we don't see and not trying to reason and use math to figure out what's missing? Feels like we're introducing chances for the AI to hallucinate or something."

**New Approach**: Log validation warnings that display visually in the review UI, allowing the reviewer to inspect the actual receipt image with bounding boxes to identify what's missing.

## Architecture

### 1. Database Schema

#### Migration 008: Add validation_warnings Column
```sql
-- Added to curlys_corp.receipts and curlys_soleprop.receipts
validation_warnings JSONB

-- Format: Array of warning objects
[{
  "type": "subtotal_mismatch",
  "message": "Line items sum to $177.80 but receipt subtotal is $191.03 (missing $13.23)",
  "data": {
    "found_total": 177.80,
    "expected_total": 191.03,
    "difference": 13.23
  }
}]

-- Index for querying receipts with warnings
CREATE INDEX idx_{schema}_receipts_has_warnings
ON {schema}.receipts ((validation_warnings IS NOT NULL AND jsonb_array_length(validation_warnings) > 0))
```

#### Migration 009: Update Review View
```sql
-- Recreated materialized view with JOIN to include validation_warnings
-- Now pulls validation_warnings from receipts table via receipt_id
CREATE MATERIALIZED VIEW {schema}.view_review_receipt_line_items AS
SELECT
  -- ... existing fields ...
  jsonb_build_object(
    -- ... existing details ...
    'validation_warnings', r.validation_warnings  -- ← NEW
  ) AS details,
  -- ... rest of view ...
FROM {schema}.receipt_line_items rli
JOIN {schema}.receipts r ON rli.receipt_id = r.id  -- ← JOIN added
WHERE rli.requires_review = true
```

### 2. Parser Changes

#### packages/parsers/vendors/base_parser.py
```python
def handle_missing_line_items(
    self,
    lines: list[ReceiptLine],
    subtotal: Decimal,
    tolerance: Decimal = Decimal('0.10'),
    vendor_name: Optional[str] = None
) -> tuple[list[ReceiptLine], Optional[dict]]:
    """
    IMPORTANT: Does NOT create placeholder lines. Instead, returns a validation
    warning dict that the parser should include in ReceiptNormalized.validation_warnings.

    Returns:
        Tuple of (original lines, validation_warning dict or None)
    """
    line_item_total = sum(
        line.line_total for line in lines
        if line.line_type in [LineType.ITEM, LineType.FEE]
    )

    missing_amount = subtotal - line_item_total

    if abs(missing_amount) > tolerance:
        logger.warning("subtotal_mismatch_detected", ...)

        warning = {
            "type": "subtotal_mismatch",
            "message": f"Line items sum to ${float(line_item_total):.2f} but receipt subtotal is ${float(subtotal):.2f} (missing ${abs(float(missing_amount)):.2f})",
            "data": {
                "found_total": float(line_item_total),
                "expected_total": float(subtotal),
                "difference": float(abs(missing_amount))
            }
        }
        return lines, warning

    return lines, None
```

#### packages/parsers/vendors/walmart_parser.py
```python
# Capture warning from base parser
lines, validation_warning = self.handle_missing_line_items(
    lines=lines, subtotal=subtotal, vendor_name="Walmart"
)

# Build warnings list
validation_warnings = [validation_warning] if validation_warning else None

# Include in ReceiptNormalized
return ReceiptNormalized(
    # ... existing fields ...
    validation_warnings=validation_warnings,
)
```

### 3. Schema Updates

#### packages/common/schemas/receipt_normalized.py
```python
class ReceiptNormalized(BaseModel):
    # ... existing fields ...

    # Validation warnings (added per user feedback - don't create fake balancing lines)
    validation_warnings: Optional[List[dict]] = Field(
        default=None,
        description="Validation issues detected during parsing (e.g., subtotal mismatch)"
    )

    @validator("lines")
    def validate_lines_sum(cls, v, values):
        """
        Validate line items (removed strict sum validation per user feedback).

        Previously this would raise ValueError if line items didn't sum to subtotal.
        Now we just pass through - the parser logs a warning and stores it in
        validation_warnings field for human review.
        """
        return v  # No longer raises ValueError
```

### 4. OCR Worker Updates

#### services/worker/tasks/ocr_receipt.py
```python
async def store_receipt_results(...):
    # Add validation_warnings if present
    if parsed_receipt.validation_warnings:
        update_fields["validation_warnings"] = json.dumps(parsed_receipt.validation_warnings)
        validation_warnings_sql = ", validation_warnings = :validation_warnings::jsonb"
    else:
        validation_warnings_sql = ""

    await session.execute(
        text(f"""
            UPDATE {schema_name}.receipts
            SET
                -- ... existing fields ...
                {validation_warnings_sql},
                updated_at = NOW()
            WHERE id = :receipt_id
        """),
        update_fields
    )
```

### 5. Review UI Display

#### apps/web/app/review/page.tsx
```tsx
{/* Validation Warnings */}
{item.details?.validation_warnings && item.details.validation_warnings.length > 0 && (
  <div className="mt-3 p-3 bg-red-50 border border-red-300 rounded">
    <div className="text-sm font-bold text-red-900 mb-2">⚠️ Validation Issues:</div>
    <div className="space-y-2">
      {item.details.validation_warnings.map((warning: any, idx: number) => (
        <div key={idx} className="text-sm text-red-800">
          <div className="font-medium">{warning.message}</div>
          {warning.data && warning.type === 'subtotal_mismatch' && (
            <div className="mt-1 text-xs bg-red-100 p-2 rounded">
              <div>Found: ${warning.data.found_total}</div>
              <div>Expected: ${warning.data.expected_total}</div>
              <div className="font-bold">Missing: ${warning.data.difference}</div>
            </div>
          )}
        </div>
      ))}
    </div>
  </div>
)}
```

## Reprocessing Script

A new script allows reprocessing existing receipts with updated OCR/parsing logic:

```bash
# Run inside worker container
docker compose exec worker python scripts/reprocess_receipt.py <receipt_id>

# Example
docker compose exec worker python scripts/reprocess_receipt.py acafec2a-00e1-4484-96e7-ccb05e43185f
```

The script:
1. Fetches existing receipt from database
2. Deletes old line items
3. Re-runs full OCR → parsing → categorization pipeline
4. Stores fresh results with updated validation warnings

## Testing

### Test Receipt: Walmart (acafec2a-00e1-4484-96e7-ccb05e43185f)

**Before**:
- 41 line items (40 real + 1 fake "$13.23 faded items" balancing line)
- Validation would fail if fake line wasn't added

**After Reprocessing**:
- 40 real line items (no fake line)
- Validation warning in database:
  ```json
  {
    "type": "subtotal_mismatch",
    "message": "Line items sum to $177.80 but receipt subtotal is $191.03 (missing $13.23)",
    "data": {
      "found_total": 177.80,
      "expected_total": 191.03,
      "difference": 13.23
    }
  }
  ```
- Review UI displays red alert box with breakdown
- Bounding boxes allow visual inspection of actual receipt

### Database Verification
```sql
-- Check validation warnings
SELECT vendor, subtotal, total, validation_warnings
FROM curlys_corp.receipts
WHERE id = 'acafec2a-00e1-4484-96e7-ccb05e43185f';

-- Refresh materialized view
REFRESH MATERIALIZED VIEW curlys_corp.view_review_receipt_line_items;

-- Query review queue
SELECT * FROM curlys_corp.view_review_receipt_line_items
WHERE details->>'validation_warnings' IS NOT NULL;
```

## Benefits

1. **No Hallucination Risk**: System doesn't try to infer or create fake data
2. **Visual Context**: Reviewer can see bounding boxes on actual receipt image
3. **Accurate Records**: All line items are real OCR extractions
4. **Better Debugging**: Clear indication of where OCR failed vs. where items are actually missing
5. **Audit Trail**: Validation warnings are stored permanently in database

## Future Enhancements

1. **Side-by-Side View**: Display receipt image alongside OCR text line-by-line for easier comparison
2. **Additional Warning Types**:
   - `ocr_confidence_low`: When overall OCR confidence < threshold
   - `tax_mismatch`: When calculated tax doesn't match receipt tax line
   - `date_ambiguous`: When date extraction is uncertain
   - `vendor_uncertain`: When vendor detection confidence is low
3. **Warning Actions**: Allow reviewers to mark warnings as "false positive" or "acknowledged"
4. **Analytics**: Track which vendors/receipt types have highest warning rates

## Migration Path

### New Receipts
All receipts processed after this change automatically use the new validation warnings system.

### Existing Receipts
Run the reprocess script to update old receipts:
```bash
# Find receipts that might have fake balancing lines
SELECT r.id, r.vendor, r.date, rli.description
FROM curlys_corp.receipts r
JOIN curlys_corp.receipt_line_items rli ON rli.receipt_id = r.id
WHERE rli.description ILIKE '%faded%' OR rli.description ILIKE '%missing%';

# Reprocess each one
docker compose exec worker python scripts/reprocess_receipt.py <receipt_id>
```

## Related Files

- `packages/parsers/vendors/base_parser.py:176-233` - Validation warning generation
- `packages/common/schemas/receipt_normalized.py:137-141,154-166` - Schema definition
- `infra/db/migrations/versions/008_add_validation_warnings.py` - Database migration
- `infra/db/migrations/versions/009_add_validation_warnings_to_review_view.py` - View update
- `apps/web/app/review/page.tsx:438-457` - UI display
- `services/worker/tasks/ocr_receipt.py:557-562` - Worker storage logic
- `scripts/reprocess_receipt.py` - Reprocessing tool

## API Response Example

```json
{
  "items": [{
    "id": "receipt_line_item:curlys_corp:2d58dcda-960c-438a-a7f4-80fd7e1390e2",
    "type": "receipt_line_item",
    "entity": "corp",
    "summary": "\"CANADA DRY A\" → beverage_soda",
    "details": {
      "receipt_id": "acafec2a-00e1-4484-96e7-ccb05e43185f",
      "description": "CANADA DRY A",
      "line_total": 6.98,
      "validation_warnings": [{
        "type": "subtotal_mismatch",
        "message": "Line items sum to $177.80 but receipt subtotal is $191.03 (missing $13.23)",
        "data": {
          "found_total": 177.80,
          "expected_total": 191.03,
          "difference": 13.23
        }
      }]
    },
    "vendor": "Walmart",
    "date": "2025-10-10T00:00:00",
    "amount": "6.98"
  }]
}
```

## UI Screenshots

**Before**: Review UI would show a fake line item:
```
41 line items including:
- Line 41: "$13.23 faded items" (FAKE - created by system)
```

**After**: Review UI shows validation warning:
```
⚠️ Validation Issues:
Line items sum to $177.80 but receipt subtotal is $191.03 (missing $13.23)

  Found: $177.80
  Expected: $191.03
  Missing: $13.23

40 real line items (no fake lines)
[Visual receipt image with bounding boxes for inspection]
```

## Conclusion

This architectural change improves data integrity by eliminating AI hallucination risk while providing better visual context for human reviewers to identify actual OCR failures or physically missing receipt items.
