# Walmart Parser - What Went Wrong

## Critical Mistakes Found

### 1. **Testing with Low-Quality OCR** ❌
**What they did:** Used Tesseract (84% confidence) during development
**Result:** OCR errors like `$65.77` instead of `$5.77` led to wasted debugging time
**What to do:** ALWAYS use AWS Textract (95%+ confidence) during parser development. Only fall back to Tesseract in production when Textract unavailable.

### 2. **Wrote Regex Before Looking at Real Data** ❌
**What they did:** Expected format `DESC AMOUNT TAXCODE`
**Actual format:** `DESC UPC $AMOUNT TAXCODE`
**Result:** Extracted 0 items, created $47 placeholder for entire subtotal
**What to do:** Extract OCR text from 2-3 sample receipts FIRST, study the actual format in a text editor, THEN write regex patterns.

### 3. **Tax Extraction Regex Was Too Greedy** ❌
**What they did:** Pattern `[^0-9\n]*` matched "14.0000" from `HST 14.0000 % $13.00`
**Result:** Extracted $14.00 tax instead of $13.00, total off by $1
**What to do:** When multiple numbers appear near a label, anchor to the `$` symbol: `[^$\n]*\$(\d+\.\d{2})`

### 4. **Missed Promotional Line Format** ❌
**What they did:** Excluded all promo lines with `PEPSI.*FOR` in NON_ITEM_PREFIX
**Result:** Lost $7.84 discount, created phantom placeholder
**What to do:** Study non-standard lines (promos, discounts, adjustments) and create separate regex patterns for each format variant.

### 5. **Didn't Validate Against Real Receipts End-to-End** ❌
**What they did:** Assumed placeholder system would "just work"
**Result:** Parser created placeholders for missing data instead of extracting actual items
**What to do:** Test full parsing flow (OCR → parse → validate totals) with real receipts BEFORE considering parser complete.

## Quick Checklist for Next Parser

1. ✅ Get 2-3 real receipt samples from vendor
2. ✅ Run AWS Textract OCR on ALL samples
3. ✅ Study OCR output in text editor - identify ALL line formats (items, promos, deposits, weighted items)
4. ✅ Write regex for EACH format variant (not just main items)
5. ✅ Test extraction: do line totals sum to subtotal? (±$0.02)
6. ✅ Test tax/total: does subtotal + tax = total? (±$0.02)
7. ✅ Test vendor detection: does it false-match other vendors?

## What They Got Right ✅

- Used `BaseReceiptParser` properly
- Implemented tax flag inference
- Created deposit detection logic
- Used structured logging
- Wrote clear docstrings

**Bottom Line:** The guide was followed for structure, but real-world data validation was skipped. Always test with high-quality OCR on actual receipts BEFORE writing code.
