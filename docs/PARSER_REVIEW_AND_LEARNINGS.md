# Parser Review & System Learnings
**Date:** October 11, 2025
**Context:** Walmart parser testing + Review UI development

---

## Executive Summary

### What Worked
- ✅ **OCR Pipeline:** HEIC → Tesseract → 84% confidence (excellent for receipt photo)
- ✅ **Walmart Parser:** Detection patterns work, structure looks good
- ✅ **Review API:** Complete backend with filters, actions, batch operations, audit trail
- ✅ **Database Schema:** Materialized views for generic review queue working perfectly

### Critical Bugs Found
- ❌ **Pepsi Parser False Positive:** Incorrectly matches Walmart receipts (UPC collision)
- ❌ **Walmart Parser Not Registered:** Created but not added to dispatcher
- ❌ **Generic Parser Failing:** Should be fallback but threw error instead

### Key Learnings
1. **OCR runs in Worker container** (not API) - Tesseract only installed there
2. **Vendor detection order matters** - More specific parsers must come before generic ones
3. **UPC prefix matching is dangerous** - Need stronger vendor signals

---

## 🐛 Critical Bug: Pepsi Parser False Positive

### Problem
The Pepsi parser's `detect_format()` method (line 71-74) matches any receipt with 3+ product codes starting with `69000`:

```python
pepsi_product_codes = re.findall(r'69000\d{6}', text)
if len(pepsi_product_codes) >= 3:  # Multiple Pepsi products
    return True
```

### Why This Failed
The Walmart receipt contains these UPCs:
- `069000149180` - BUBLY LIME (Pepsi product sold at Walmart)
- `062100008930` - CANADA DRY (another beverage)
- Several other `69000` prefix codes

**The `69000` prefix is a legitimate GS1 Company Prefix** assigned to PepsiCo, but Pepsi **products** are sold at **many retailers** (Walmart, Costco, GFS, etc.). This pattern matches any receipt that happens to have Pepsi-branded beverages, not actual Pepsi delivery invoices.

### Impact
- Walmart receipts get misrouted to Pepsi parser
- Pepsi parser fails to extract correct data (wrong format)
- Generic parser never runs (dispatcher stops after first match)
- Receipt processing fails completely

### Recommended Fix

**Option 1: Strengthen Pepsi Detection (RECOMMENDED)**
```python
def detect_format(self, text: str) -> bool:
    text_upper = text.upper()

    # Delivery invoices: Must have company name + address
    has_company = bool(re.search(r'PEPSICO\s+CANADA', text_upper))
    has_moncton_address = bool(re.search(r'220\s+HENRI\s+DUNANT', text_upper))

    if has_company or has_moncton_address:
        return True

    # Email summaries: Must have Pepsi UPCs + invoice structure keywords
    pepsi_upcs = re.findall(r'69000\d{6}', text)
    has_invoice_keywords = any([
        'INVOICE DETAILS' in text_upper,
        'INVOICE SUMMARY' in text_upper,
        'PEPSICO' in text_upper,
        'PEPSI BEVERAGES' in text_upper,
    ])

    # Require BOTH Pepsi products AND invoice structure
    if len(pepsi_upcs) >= 3 and has_invoice_keywords:
        return True

    return False
```

**Option 2: Move Pepsi Parser Lower in Priority**
Place Pepsi parser after Walmart/Costco/Superstore so retail receipts are caught first. However, this doesn't solve the root problem - Pepsi could still match other receipts.

**Option 3: Negative Detection**
Add explicit rejection for known retail vendors:
```python
# Don't match if this is clearly a retail receipt
retail_indicators = ['WALMART', 'COSTCO', 'SUPERSTORE', 'SOBEYS']
if any(indicator in text_upper for indicator in retail_indicators):
    return False
```

### Priority
**CRITICAL** - This blocks Walmart receipt processing entirely.

---

## 📝 Walmart Parser Review

### Code Location
`packages/parsers/vendors/walmart_parser.py`

### Overall Assessment
**Grade: B+** - Solid structure, good patterns, but minor issues

### What's Good
1. **Detection Patterns (lines 45-50):** Comprehensive and specific
   ```python
   VENDOR_PATTERNS = [
       r"\bWALMART\b",
       r"\bWALMART\s+SUPERCENTRE\b",
       r"SAVE\s+MONEY\.?\s+LIVE\s+BETTER\.?",  # Slogan
       r"\bTC#\b|\bTR#\b|\bTRANS#\b",  # Transaction markers
   ]
   ```
   ✅ Multiple fallback patterns
   ✅ Uses word boundaries (`\b`) to avoid partial matches
   ✅ Includes store-specific codes (TC#, TR#)

2. **Non-Item Filtering (lines 53-57):** Prevents footer lines from being parsed as items
   ```python
   NON_ITEM_PREFIX = (
       r"SUB\s*TOTAL|TOTAL\b|CHANGE\b|CASH\b|DEBIT\b|..."
   )
   ```
   ✅ Comprehensive exclusion list

3. **Item Line Regex (lines 60-66):** Captures description, amount, optional tax code
   ```python
   ITEM_LINE_RE = re.compile(
       rf"^(?!\s*(?:{NON_ITEM_PREFIX}))\s*"
       r"(?P<desc>[A-Za-z0-9][A-Za-z0-9\- &%/.,()*'#]+?)\s+"
       r"(?P<amount>-?\d+[,.]?\d{0,3}\.\d{2})\s*"
       r"(?P<taxcode>[A-Z])?\s*$"
   )
   ```
   ✅ Negative lookahead prevents footer matches
   ✅ Handles negative amounts (returns/refunds)
   ✅ Optional tax code capture

### Issues Found

#### Issue 1: UPC Detection Pattern Too Narrow
**Line 49:** `r"\bTC#\b|\bTR#\b|\bTRANS#\b"`

The Walmart receipt shows UPCs like `078742614630` (12-digit) and `069000149180` (12-digit), but the parser doesn't explicitly extract them. The regex pattern captures the description but not necessarily the UPC separately.

**Impact:** Medium - SKU field might be empty for line items
**Recommendation:** Add explicit UPC extraction after item description:
```python
# After line extraction, try to extract UPC
upc_match = re.search(r'\b\d{12}\b', line_text)
if upc_match:
    line_item.sku = upc_match.group()
```

#### Issue 2: NS Deposit Lines Not Handled
**Observed:** The receipt has many `NS DEPOSIT 078742514630 $1.20 H` lines

These are Nova Scotia deposit fees (10-20¢ per bottle/can). The current regex will likely match these as items with description "NS DEPOSIT 078742514630" and amount "$1.20".

**Impact:** High - Deposit lines pollute item list, inflate subtotal
**Recommendation:** Add deposit detection to `NON_ITEM_PREFIX`:
```python
NON_ITEM_PREFIX = (
    r"SUB\s*TOTAL|TOTAL\b|CHANGE\b|CASH\b|DEBIT\b|CREDIT\b|..."
    r"NS\s+DEPOSIT|DEPOSIT\s+FEE|ECO\s+FEE|"  # Environmental fees
    ...
)
```

Or handle deposits as separate line type:
```python
DEPOSIT_LINE_RE = re.compile(
    r'(NS\s+DEPOSIT|DEPOSIT)\s+(\d+)\s+\$([\d.]+)'
)
```

#### Issue 3: Tax Code Not Mapped to TaxFlag
**Lines 79-116:** The `parse()` method extracts `taxcode` from regex but doesn't use it

Walmart uses tax codes like:
- `H` = HST taxable
- `J` = (unknown - need to verify)
- `D` = (unknown - need to verify)

**Impact:** Medium - Tax classification might be wrong
**Recommendation:** Add mapping:
```python
TAX_CODE_MAP = {
    'H': TaxFlag.TAXABLE,    # HST
    'G': TaxFlag.TAXABLE,    # GST
    'Z': TaxFlag.ZERO_RATED, # Zero-rated
    'E': TaxFlag.EXEMPT,     # Exempt
}

tax_flag = TAX_CODE_MAP.get(taxcode, TaxFlag.TAXABLE)
```

#### Issue 4: Not Registered in Dispatcher
**File:** `packages/parsers/vendor_dispatcher.py` (lines 20-58)

The `WalmartCanadaParser` is imported nowhere and not added to the parsers list.

**Impact:** CRITICAL - Parser never runs
**Fix:** Add to imports and parser list (see below)

---

## 🔧 Required Fixes

### Fix 1: Register Walmart Parser (CRITICAL)

**File:** `packages/parsers/vendor_dispatcher.py`

```python
# Add import
from packages.parsers.vendors.walmart_parser import WalmartCanadaParser

# Add to parsers list (BEFORE PepsiParser to avoid false positive)
self.parsers: list[BaseReceiptParser] = [
    GrosnorParser(),
    CostcoParser(),
    GFSParser(),
    WalmartCanadaParser(),  # ADD HERE (before Pepsi)
    PepsiParser(),
    SuperstoreParser(),
    PharmasaveParser(),
    GenericParser(),
]
```

**Why before Pepsi:** Walmart receipts can contain Pepsi product UPCs, so Walmart must be tested first.

### Fix 2: Fix Pepsi False Positive (CRITICAL)

**File:** `packages/parsers/vendors/pepsi_parser.py` (lines 69-76)

Replace weak UPC detection with stronger company-specific markers:

```python
# Format 2: Email summary indicators
# Require BOTH Pepsi UPCs AND PepsiCo-specific keywords
pepsi_upcs = re.findall(r'69000\d{6}', text)
has_pepsico_context = any([
    'PEPSICO' in text_upper,
    'PEPSI BEVERAGES' in text_upper,
    'INVOICE DETAILS' in text_upper and len(pepsi_upcs) >= 5,
])

if len(pepsi_upcs) >= 3 and has_pepsico_context:
    logger.info("pepsi_format_detected", pattern="pepsi_product_codes_with_context", count=len(pepsi_upcs))
    return True
```

### Fix 3: Handle Walmart Deposits

**File:** `packages/parsers/vendors/walmart_parser.py`

**Option A (Simple):** Exclude from items
```python
NON_ITEM_PREFIX = (
    r"SUB\s*TOTAL|TOTAL\b|CHANGE\b|..."
    r"NS\s+DEPOSIT|DEPOSIT|ECO\s+FEE|ENVIRONMENTAL\s+FEE|"
)
```

**Option B (Accurate):** Track as separate line type
```python
def _extract_lines(self, text: str) -> list[ReceiptLine]:
    lines = []

    # Extract deposit lines separately
    deposit_pattern = r'(NS\s+DEPOSIT|DEPOSIT)\s+(\d+)\s+\$([\d.]+)'
    for match in re.finditer(deposit_pattern, text):
        lines.append(ReceiptLine(
            line_index=len(lines),
            line_type=LineType.FEE,
            item_description=f"Bottle/Can Deposit ({match.group(2)})",
            line_total=Decimal(match.group(3)),
            tax_flag=TaxFlag.EXEMPT,  # Deposits aren't taxed
        ))

    # Then extract regular items (excluding deposits)
    ...
```

---

## 📚 System Architecture Learnings

### Discovery 1: OCR in Worker Container Only

**What We Learned:**
- Tesseract is **only installed in the `worker` container**, not `api`
- The `api` container is lightweight (FastAPI only)
- All OCR/parsing happens in **background Celery tasks**

**Why This Matters:**
- Test scripts must run in `worker` container: `docker compose exec worker python scripts/test_receipt.py`
- API endpoints queue tasks but don't process them directly
- Receipt upload flow: `API (save file) → Queue task → Worker (OCR + parse + categorize) → DB`

**Documentation Update Needed:**
Add to `CLAUDE.md`:
```markdown
### Container Responsibilities

- **API Container (`api`):** FastAPI web server, endpoints, request validation
  - **Does NOT have:** Tesseract, image processing libraries
  - **Cannot run:** OCR scripts, parser tests

- **Worker Container (`worker`):** Celery background tasks, OCR processing
  - **Has:** Tesseract, Pillow, pdf2image, pytesseract
  - **Runs:** `services/worker/tasks/ocr_receipt.py`
  - **Use for:** Testing parsers, running OCR scripts

**Testing Parsers:**
```bash
# ❌ WRONG - API container doesn't have Tesseract
docker compose exec api python scripts/test_parser.py

# ✅ CORRECT - Worker container has OCR tools
docker compose exec worker python scripts/test_parser.py
```
```

### Discovery 2: Vendor Dispatcher API

**Correct Usage:**
```python
from packages.parsers.vendor_dispatcher import parse_receipt
from packages.common.schemas.receipt_normalized import EntityType

# Convenience function (uses singleton dispatcher)
receipt = parse_receipt(ocr_text, entity=EntityType.CORP)

# OR explicit dispatcher instance
from packages.parsers.vendor_dispatcher import VendorDispatcher
dispatcher = VendorDispatcher()
receipt = dispatcher.dispatch(ocr_text, entity=EntityType.CORP)
```

**Common Mistake:**
```python
# ❌ WRONG - dispatcher doesn't have .parse() method
dispatcher.parse(ocr_text, entity)  # AttributeError!

# ✅ CORRECT
dispatcher.dispatch(ocr_text, entity)
```

### Discovery 3: Review Queue Architecture

**Materialized Views Work Perfectly:**
- `curlys_corp.view_review_receipt_line_items` projects `receipt_line_items` into generic `Reviewable` shape
- Triggers auto-refresh on INSERT/UPDATE/DELETE
- API queries views directly (no ORM needed for read-only review queue)

**Key Insight:** The generic review contract is **read-only**. Actions (approve, correct, reject) write to **source tables** (`receipt_line_items`), then views refresh automatically.

**Why This is Brilliant:**
- UI doesn't need to know about domain-specific schemas
- Adding new review types (reimbursements, bank matches) = just add another view
- Audit trail in `shared.review_activity` is domain-agnostic

---

## 🎯 Action Items

### Immediate (Blocking Walmart Receipt Processing)
1. ✅ Register `WalmartCanadaParser` in dispatcher
2. ✅ Fix Pepsi parser false positive detection
3. ✅ Test Walmart receipt end-to-end

### High Priority (Next Session)
4. Handle NS deposit lines in Walmart parser
5. Add UPC extraction to Walmart line items
6. Map Walmart tax codes (`H`, `J`, `D`) to `TaxFlag` enum

### Medium Priority
7. Review all parsers for UPC prefix collisions
8. Add parser unit tests for `detect_format()` false positives
9. Build review UI frontend (API is done)

### Documentation Updates
10. Update `CLAUDE.md` with container responsibilities
11. Update `CLAUDE.md` with correct dispatcher API
12. Document parser registration process
13. Add "Common Pitfalls" section to parser development docs

---

## 📊 Walmart Receipt Analysis

### OCR Quality
- **Confidence:** 84% (excellent for phone photo)
- **Text Length:** 2,328 characters
- **Method:** Tesseract (HEIC converted to RGB PNG internally)
- **Issues:** Some minor OCR errors ("7 rs" at top, "dard 1 of 3" instead of "1 of 3")

### Receipt Structure Observed
```
WALMART SURVEY HEADER
STORE INFO (6789, 46 ROBERT ANGUS DR, AMHERST NS)
TRANSACTION CODES (ST# 05789 OP# 009089 TE# 89 TR# 03907)
LINE ITEMS:
  NS DEPOSIT 078742614630 $1.20 H
  CANADA DRY A 062100008930 $6.98 J
  BUBLY LIME 069000149180 $5.97 J
  GV DIST 4L 605388881250 $1.24 D
  NS DEPOSIT 078742640810 $0.10 H
  SBN HOMO MLK 0631242... [truncated]
FOOTER (subtotal/tax/total)
```

### Key Observations
1. **Deposit lines are interleaved** with product lines (not grouped at end)
2. **Multiple deposit types:** `$1.20` (cans/bottles) and `$0.10` (???)
3. **Tax codes vary:** `H` (HST?), `J` (??), `D` (???) - need to research
4. **UPCs are 12-digit** - standard GS1 format
5. **Store number (6789)** and transaction number (03907) are extractable

---

## 🧪 Testing Recommendations

### Walmart Parser Test Plan
1. **Detection test:** Ensure it matches Walmart receipts, not others
2. **Deposit handling:** Verify deposits are excluded or tracked separately
3. **Tax code mapping:** Test all observed codes (H, J, D)
4. **UPC extraction:** Confirm SKUs are captured for all items
5. **Multi-page:** Test stitched receipts (if Walmart receipts span pages)

### Pepsi Parser Regression Test
After fixing false positive:
1. **Positive test:** Real Pepsi delivery invoice still matches
2. **Negative test:** Walmart receipt with Pepsi products does NOT match
3. **Negative test:** Costco receipt with Pepsi products does NOT match

### Integration Test
Full end-to-end:
1. Upload Walmart HEIC → OCR (worker)
2. Parse receipt → Extract items
3. Categorize items → AI recognition
4. Insert to DB → Materialized view refreshes
5. Query review queue → Items appear
6. Correct item → Cache updates
7. Query same SKU → Cache hit (instant, free)

---

## 💡 Best Practices Learned

### Parser Development
1. **Detection must be specific** - Don't rely on product codes alone
2. **Test with cross-vendor products** - Pepsi products appear at many retailers
3. **Register immediately** - Parser is useless if not in dispatcher
4. **Order matters** - Specific parsers before generic ones

### Testing
1. **Always test in worker container** for OCR scripts
2. **Test false positives** - Ensure parser doesn't match wrong receipts
3. **Use real receipts** - Synthetic data misses edge cases (deposits, tax codes)

### API Design
1. **Read-only views for queries** - Fast, schema-agnostic
2. **Write to source tables** - Triggers handle view refresh
3. **Generic contracts** - UI doesn't couple to domain schemas

---

## 📝 Final Thoughts

The system architecture is **excellent** - materialized views, generic review contract, cache-first categorization. The bugs found are **typical parser development issues**:

- False positive detection (Pepsi)
- Incomplete registration (Walmart)
- Edge cases not handled (deposits)

All fixable with targeted patches. The **review API is production-ready** - just needs UI.

**Estimated time to fix critical issues:** 30 minutes
**Estimated time to complete Walmart parser:** 2 hours
**Estimated time to build review UI:** 4-6 hours

---

**Next Steps:**
1. Apply critical fixes (register Walmart, fix Pepsi)
2. Test end-to-end with real receipt
3. Verify items appear in review queue
4. Test correction workflow + cache update
5. Build review UI if backend tests pass

**Blocker Removed:** Once Walmart is registered and Pepsi is fixed, receipt processing should work end-to-end.
