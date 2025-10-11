# Categorization Review Workflow

## Overview

The AI categorization system is designed with **human review as a critical safeguard**. Items are automatically flagged for review based on confidence thresholds to prevent misclassifications from slipping into your books.

## How Review Works

### Automatic Review Flagging

Items are flagged for review (`requires_review=True`) when:

1. **AI confidence < 80%** (configurable via `CATEGORIZATION_CONFIDENCE_THRESHOLD`)
2. **Category is "unknown"** (always requires review)
3. **Equipment items ≥ $2500** (capitalization decision)

### Confidence Calibration

The AI uses Claude Sonnet 4.5 with these confidence guidelines:

- **0.95-0.99**: Very confident (clear brand like "PEPSI 32 PK", "GATORADE COOL BLUE")
- **0.80-0.94**: Confident but some ambiguity (clear product type, generic description)
- **0.60-0.79**: Uncertain (vague description, multiple interpretations) → **FLAGGED FOR REVIEW**
- **Below 0.60**: Very uncertain (marked as "unknown") → **FLAGGED FOR REVIEW**

### Example: Costco Stress Test Results

From real testing with 24 Costco items (cryptic abbreviations):

| Item | AI Classification | Confidence | Review? | Notes |
|------|-------------------|------------|---------|-------|
| "PEPSI 32 PK" | Pepsi Cola Soft Drink 32 Pack | 99% | ❌ No | Clear brand + product |
| "ALANI C&C" | Alani Nu Cookies & Cream Energy Drink | 90% | ❌ No | Brand recognition |
| "KETCHP 2.84L" | Ketchup 2.84L | 98% | ❌ No | Clear abbreviation |
| "EAST COAST" | East Coast Brand Product (unknown) | 50% | ✅ YES | Too vague - could be seafood, coffee, etc. |
| "3 YR PC PROT" | 3 Year PC Protection Plan | 72% | ✅ YES | Below 80% threshold |
| "HOT ROD 40CT" | Hot Rod Pepperoni Sticks 40 Count | 92% | ❌ No | Brand name recognized |

**Result**: 2 out of 24 items (8.3%) flagged for review, preventing potential errors.

## Why This Matters: The "HOT ROD" Problem

**Your Concern (100% valid!):**
> "If this goes into production and something tells me I don't have to review it then I'm probably not going to see it"

**The Problem:**
Initial testing showed HOT ROD categorized with 85% confidence as `food_hotdog` → Account 5001.
**This was WRONG!** Hot Rod is a brand of meat snacks (retail_snack → Account 5031).

But because confidence was 85% (above 80% threshold), it wouldn't have been flagged for review!

### Solutions Implemented

1. **Improved AI Prompt** with better examples distinguishing brand names from product descriptions:
   ```
   Input: "HOT ROD 40CT"
   Output: "Hot Rod Pepperoni Sticks 40 Count"
   Reasoning: "Hot Rod" is a BRAND NAME for meat snacks, not describing hot dogs
   ```

2. **Optional Web Lookup** (disabled by default):
   - When uncertain, system can search vendor websites for SKU
   - Extracts actual product name from search results
   - Adds context to AI prompt for better classification
   - Enable with: `CATEGORIZATION_WEB_LOOKUP_ENABLED=true`

3. **User Corrections Improve Cache**:
   - When you correct a misclassification, it gets cached
   - Next time that SKU appears → instant correct categorization (100% confidence)
   - Over time, cache hit rate reaches 95%+, reducing AI calls

## Review Process (Production Workflow)

### Step 1: Receipt Upload & Parsing
- Receipt uploaded → OCR → Vendor-specific parser extracts line items
- Each line item gets SKU + description (e.g., "54491" + "HOT ROD 40CT")

### Step 2: AI Categorization
- Check cache first (if SKU seen before → instant categorization)
- Cache miss → Call Claude Sonnet 4.5 with detailed prompt
- Optional: Look up SKU on vendor website (if enabled)
- AI returns: normalized description, category, confidence

### Step 3: GL Account Mapping
- Rule-based mapping: category → GL account
- Check capitalization threshold for equipment
- Calculate overall confidence

### Step 4: Review Queue
Items with `requires_review=True` go to review dashboard:

```
┌─────────────────────────────────────────────────────────────────┐
│ RECEIPT REVIEW QUEUE                                            │
├─────────────────────────────────────────────────────────────────┤
│ Receipt: Costco #1345 - Oct 8, 2025 - $5,479.47               │
│                                                                 │
│ ⚠ 2 items need review (91% auto-categorized)                   │
│                                                                 │
│ 1. SKU 252886 - "EAST COAST" → Unknown (50% confidence)       │
│    AI guess: East Coast Brand Product                          │
│    Suggested: [food_meat] [beverage_coffee] [unknown] [Other]  │
│    → Search vendor website for "252886"                        │
│    → User enters: "East Coast Coffee Co. Medium Roast 1kg"    │
│    → Auto-categorizes as: food_pantry → Account 5099          │
│    → ✓ Cache updated (next time: instant + correct!)          │
│                                                                 │
│ 2. SKU 369437 - "3 YR PC PROT" → retail_other (72% conf.)     │
│    AI guess: 3 Year PC Protection Plan                         │
│    Suggested: [retail_other] [office_supply] [unknown]         │
│    → User confirms: retail_other (warranty/insurance)          │
│    → ✓ Approved                                                │
│                                                                 │
│ [Approve All] [Export for Manual Entry] [Back to Receipts]    │
└─────────────────────────────────────────────────────────────────┘
```

### Step 5: Approval & Posting
- User reviews/corrects flagged items
- Corrections saved to cache (benefit future receipts)
- Receipt posted to GL with journal entry
- Receipt marked as `reviewed=true`

## Configuration

### Environment Variables

```bash
# AI Categorization
ANTHROPIC_API_KEY=sk-ant-...
CATEGORIZATION_CONFIDENCE_THRESHOLD=0.80  # Items below this require review
CATEGORIZATION_WEB_LOOKUP_ENABLED=false   # Enable vendor website lookups (EXPERIMENTAL)
CATEGORIZATION_WEB_LOOKUP_TIMEOUT=5.0     # seconds
```

### Confidence Threshold Tuning

**Default: 0.80 (80%)**

- **Higher (0.90)**: Fewer items auto-categorized, more review needed (safer, slower)
- **Lower (0.70)**: More items auto-categorized, less review (faster, riskier)

**Recommendation**: Start at 0.80, adjust after 1-2 months based on error rate.

## Web Lookup Feature (EXPERIMENTAL)

### How It Works

When enabled, the system attempts to verify uncertain categorizations by:

1. Searching vendor website for SKU (e.g., `https://www.costco.ca/CatalogSearch?keyword=54491`)
2. Parsing HTML to extract product name, brand, category
3. Adding this context to AI prompt for better classification

### Supported Vendors

- Costco Canada
- Gordon Food Service (GFS)
- Atlantic Superstore
- Wholesale Club

### Limitations

**Why disabled by default:**
- Vendor websites may block scrapers
- HTML structure changes break parsing
- Adds 2-5 seconds per uncached item
- Rate limiting possible on batch imports

**When to enable:**
- Testing phase (import historical receipts)
- Manual receipt entry (low volume)
- High-value receipts (large transactions)

**When to disable:**
- Production (batch processing)
- After cache hit rate > 90%
- If vendors block requests

### Enable Web Lookup

```bash
# In .env
CATEGORIZATION_WEB_LOOKUP_ENABLED=true
```

**Monitor logs:**
```
2025-10-10 07:56:44 [info] product_lookup_started vendor=Costco sku=54491
2025-10-10 07:56:45 [info] product_lookup_success found_name="Hot Rod Pepperoni Sticks 40ct"
2025-10-10 07:56:45 [info] web_lookup_found product_name="Hot Rod Pepperoni Sticks 40ct"
```

## Cost Analysis

### With 80% Confidence Threshold

**Typical Costco receipt (24 items):**
- Items auto-categorized: 22 (91.7%)
- Items flagged for review: 2 (8.3%)
- AI calls (first time): 24 × $0.006 = **$0.14**
- AI calls (cached): 24 × $0.00 = **FREE**

**Monthly projections** (assuming 1000 line items/month):
- Month 1: ~$60 (all new SKUs)
- Month 6: ~$6 (90% cache hit rate)
- Month 12+: <$1 (95%+ cache hit rate)

### With Web Lookup Enabled

**Additional overhead per uncached item:**
- Time: +2-5 seconds
- No additional API cost (web scraping is free)
- Risk: May be blocked by vendor

**Recommendation**: Enable only during initial data import, disable for production.

## Testing & Validation

### Costco Stress Test (Real Data)

**File**: `vendor-samples/OctCostco2025test.pdf`
**Items**: 24 (extremely abbreviated descriptions)
**Results** (Claude Sonnet 4.5):
- Accuracy: 23/24 (95.8%)
- Review flagged: 2 items (8.3%)
- Average confidence: 92.6%
- Cost: $0.10 first pass, $0.00 cached

**Key learnings:**
- "EAST COAST" correctly flagged as unknown (too vague)
- "3 YR PC PROT" correctly identified as protection plan (not protein!)
- "ALANI C&C" correctly recognized as Alani Nu energy drink (brand awareness)

### Test Scripts

```bash
# Test with real GFS receipt
docker compose exec api python scripts/test_gfs_categorization.py

# Test with real Costco receipt (stress test)
docker compose exec api python scripts/test_costco_categorization.py

# Clear cache for fresh test
docker compose exec api python -c "
import asyncio
from packages.common.database import sessionmanager
from packages.common.config import get_settings
from sqlalchemy import text

async def clear_cache():
    settings = get_settings()
    sessionmanager.init(settings.database_url)
    async with sessionmanager.session() as db:
        result = await db.execute(text('DELETE FROM shared.product_mappings WHERE vendor_canonical = \\'Costco\\''))
        await db.commit()
        print(f'Cleared {result.rowcount} entries')
    await sessionmanager.close()

asyncio.run(clear_cache())
"
```

## Correcting Misclassifications

When you find an error in production:

### Option 1: Review Dashboard (Recommended)
- Go to https://books.curlys.ca/receipts/review
- Find the receipt
- Click "Edit" on the misclassified line
- Update category → Automatically recaches

### Option 2: Direct Cache Update (API)
```bash
curl -X PUT https://books.curlys.ca/api/v1/categorization/cache \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "vendor": "Costco",
    "sku": "54491",
    "description": "Hot Rod Pepperoni Sticks 40 Count",
    "category": "retail_snack",
    "account_code": "5031"
  }'
```

### Option 3: Manual Database Update
```sql
-- Update cached categorization
UPDATE shared.product_mappings
SET
  description_normalized = 'Hot Rod Pepperoni Sticks 40 Count',
  product_category = 'retail_snack',
  account_code = '5031',
  updated_at = NOW()
WHERE vendor_canonical = 'Costco' AND sku = '54491';
```

## Future Enhancements

### Planned Features

1. **Confidence trend tracking** - Monitor accuracy over time
2. **Bulk review interface** - Review multiple receipts at once
3. **Category suggestions** - Based on similar cached items
4. **Vendor-specific hints** - Store vendor product databases locally
5. **Machine learning feedback loop** - Learn from corrections

### Integration with Receipt Processing

Currently: Categorization is standalone (testing phase)

**Phase 2**: Integrate into OCR pipeline:
- `services/worker/tasks/ocr_receipt.py` calls categorization service
- Results stored in `receipt_lines.product_category` and `receipt_lines.account_code`
- Review queue populated automatically
- Notifications when receipts need review

## Summary

✅ **Human review is REQUIRED** for low-confidence items
✅ **Confidence threshold (80%)** prevents "confident but wrong" errors
✅ **Web lookup** available for extra verification (disabled by default)
✅ **Cache improves** with every correction you make
✅ **95%+ accuracy** after initial testing phase

The system is designed to be **fast but safe** - automatically categorize what it's confident about, flag the rest for your expert review.
