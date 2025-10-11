# Parser Architecture Overhaul - Critical Changes

**Date:** 2025-10-11
**Status:** DECISION REQUIRED - Major Architecture Change

## Problem Statement

Two critical flaws discovered during Walmart parser testing:

1. **Tesseract OCR produces garbage data** ($65.77 vs $5.77, missing items)
2. **UPC-based vendor detection is fundamentally broken** (Pepsi products sold at Walmart → false positive)

## Decision 1: Textract-Only for Paper Receipts ✅

### Current State
- Tesseract primary, Textract fallback (based on confidence threshold)
- Tesseract 84% confidence still parsed (bad data in → garbage review out)

### New Policy
**Paper receipts (photos/scans) MUST use AWS Textract exclusively.**

**Rationale:**
- Every OCR error creates a manual review task
- Bad OCR = wasted AI categorization calls
- Bad OCR = wasted human review time
- Textract cost: ~$0.0015/page vs manual review cost: 2-5 minutes/receipt
- ROI: Spending $0.0015 to save 3 minutes is a no-brainer

**Implementation:**
```python
# OLD: Try Tesseract first
if tesseract.confidence < 0.90:
    result = textract.extract_text(file)

# NEW: Paper receipts always use Textract
if file_type in ['jpg', 'png', 'heic', 'tiff']:
    result = textract.extract_text(file)  # No Tesseract option
elif file_type == 'pdf':
    # PDFs may have embedded text - try direct extraction first
    result = try_pdf_text_extraction() or textract.extract_text(file)
```

**Exceptions:**
- PDF receipts with embedded text → direct text extraction (free, 100% accurate)
- Email-based invoices (already text) → no OCR needed
- Development/testing only → Tesseract acceptable with warnings

---

## Decision 2: Vendor Name-Based Detection (Major Overhaul) ✅

### Current State (BROKEN)
Parsers detect vendor by looking for product patterns:
- Pepsi parser: "3+ UPCs starting with 69000" → FALSE POSITIVES (Walmart sells Pepsi!)
- Costco parser: "KIRKLAND" in description → works, but fragile
- GFS parser: "GFS" vendor name → correct approach

### Root Cause
**Every receipt/invoice has the vendor's name/address printed on it.**
Looking at product UPCs is backwards - we should look at WHO ISSUED THE RECEIPT.

### New Architecture

#### Stage 1: Vendor Identification (NEW)
Extract vendor identity markers from receipt header/footer:
- Vendor name (WALMART, PEPSICO CANADA, GORDON FOOD SERVICE)
- Vendor address (unique street addresses)
- Vendor phone numbers
- Vendor tax IDs (GST/HST registration numbers)
- Receipt format markers (TC#, INVOICE #, ROUTE #)

#### Stage 2: Parser Dispatch
Route to vendor-specific parser based on identified vendor name, NOT products.

### Implementation Plan

#### Step 1: Create Vendor Registry
```python
# packages/parsers/vendor_registry.py

VENDOR_PATTERNS = {
    "walmart": {
        # Name patterns - REQUIRED (must match at least one)
        "name_patterns": [
            r"\bWALMART\b",
            r"WALMART\s+SUPERCENTRE",
            r"WAL-?MART",
        ],
        # Supporting patterns - OPTIONAL (boost confidence)
        "receipt_patterns": [r"\bTC#\s*\d+", r"\bTR#\s*\d+"],  # Unique receipt format
        "gst_patterns": [r"GST/HST\s+137466199"],  # Corporate tax ID (same for all locations)
        "slogans": [r"SAVE\s+MONEY.*LIVE\s+BETTER"],
        # Address/phone NOT included - varies by location
    },
    "pepsico": {
        "name_patterns": [
            r"PEPSICO\s+CANADA",
            r"PEPSI.*BEVERAGES",
            r"PEPSI-COLA\s+CANADA",
        ],
        "receipt_patterns": [r"INVOICE\s*#\s*\d{8}", r"ROUTE\s*#\s*\d+"],
        "company_indicators": [r"BEVERAGES.*BREUVAGES"],
        # Address varies by distribution center - not used
    },
    "costco": {
        "name_patterns": [
            r"\bCOSTCO\b",
            r"COSTCO\s+WHOLESALE",
        ],
        "receipt_patterns": [r"MEMBER\s*#"],
        "gst_patterns": [r"GST/HST.*10846\s*0400"],  # Corporate tax ID
        "product_patterns": [r"\bKIRKLAND\b"],  # Kirkland = Costco exclusive
    },
    "gfs": {
        "name_patterns": [
            r"GORDON\s+FOOD\s+SERVICE",
            r"\bGFS\b",
            r"GORDON.*FOOD",
        ],
        "receipt_patterns": [r"INVOICE\s+NUMBER", r"CUSTOMER\s+NUMBER"],
    },
    "superstore": {
        "name_patterns": [
            r"ATLANTIC\s+SUPERSTORE",
            r"\bSUPERSTORE\b",
            r"LOBLAWS",  # Parent company
        ],
        "receipt_patterns": [r"PC\s+OPTIMUM", r"OPTIMUM\s+#"],
        "gst_patterns": [r"GST/HST.*10015.*2750"],  # Loblaws corporate
    },
    # ... more vendors
}
```

#### Step 2: Vendor Identifier Service
```python
class VendorIdentifier:
    """
    Identify vendor from receipt header/footer markers.

    Strategy:
    1. Vendor name is REQUIRED (works across all locations)
    2. Supporting patterns (receipt format, tax ID, slogans) boost confidence
    3. Address/phone NOT used (varies by location)

    Scoring:
    - Name match = 10 points (REQUIRED for identification)
    - Corporate tax ID = 7 points (unique, works across locations)
    - Receipt format = 5 points (e.g., TC#, MEMBER #)
    - Slogans/indicators = 3 points (e.g., "SAVE MONEY LIVE BETTER")
    - Exclusive products = 2 points (e.g., KIRKLAND for Costco)

    Threshold: 10+ points required (at minimum, name must match)
    """

    def identify_vendor(self, ocr_text: str) -> Optional[str]:
        """
        Returns: vendor_key (e.g., "walmart", "pepsico") or None
        """
        scores = {}

        for vendor_key, patterns in VENDOR_PATTERNS.items():
            score = 0
            matched_patterns = []

            # Name match = 10 points (REQUIRED)
            name_matches = [p for p in patterns.get("name_patterns", []) if re.search(p, ocr_text, re.I)]
            if name_matches:
                score += 10
                matched_patterns.append(f"name:{name_matches[0]}")

            # Corporate tax ID = 7 points (unique, same across all locations)
            gst_matches = [p for p in patterns.get("gst_patterns", []) if re.search(p, ocr_text, re.I)]
            if gst_matches:
                score += 7
                matched_patterns.append("gst")

            # Receipt format = 5 points (unique format markers)
            receipt_matches = [p for p in patterns.get("receipt_patterns", []) if re.search(p, ocr_text, re.I)]
            if receipt_matches:
                score += 5
                matched_patterns.append("receipt_format")

            # Slogans/company indicators = 3 points
            slogan_matches = [p for p in patterns.get("slogans", []) if re.search(p, ocr_text, re.I)]
            if slogan_matches:
                score += 3
                matched_patterns.append("slogan")

            indicator_matches = [p for p in patterns.get("company_indicators", []) if re.search(p, ocr_text, re.I)]
            if indicator_matches:
                score += 3
                matched_patterns.append("company_indicator")

            # Exclusive products = 2 points (e.g., Kirkland only at Costco)
            product_matches = [p for p in patterns.get("product_patterns", []) if re.search(p, ocr_text, re.I)]
            if product_matches:
                score += 2
                matched_patterns.append("exclusive_product")

            if score > 0:
                scores[vendor_key] = {"score": score, "patterns": matched_patterns}

        # Return highest scoring vendor if score >= 10 (must have name match)
        if scores:
            best_vendor = max(scores.items(), key=lambda x: x[1]["score"])
            if best_vendor[1]["score"] >= 10:
                logger.info("vendor_identified",
                           vendor=best_vendor[0],
                           score=best_vendor[1]["score"],
                           patterns=best_vendor[1]["patterns"])
                return best_vendor[0]

        logger.warning("vendor_not_identified",
                      top_scores=[(k, v["score"]) for k, v in sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)[:3]])
        return None  # Unknown vendor -> GenericParser
```

#### Step 3: Update VendorDispatcher
```python
class VendorDispatcher:
    def __init__(self):
        self.identifier = VendorIdentifier()
        self.parsers = {
            "walmart": WalmartCanadaParser(),
            "pepsico": PepsiParser(),
            "costco": CostcoParser(),
            "gfs": GFSParser(),
            # ...
            "generic": GenericParser(),
        }

    def dispatch(self, ocr_text: str, entity: EntityType) -> ReceiptNormalized:
        # NEW: Identify vendor first
        vendor_key = self.identifier.identify_vendor(ocr_text)

        if vendor_key and vendor_key in self.parsers:
            logger.info("vendor_identified", vendor=vendor_key)
            parser = self.parsers[vendor_key]
        else:
            logger.warning("vendor_unknown", using="generic_parser")
            parser = self.parsers["generic"]

        return parser.parse(ocr_text, entity)
```

#### Step 4: Remove detect_format() from Parsers
Parsers no longer need `detect_format()` - they're invoked directly by vendor key.

**Optional:** Keep `detect_format()` as a validation method:
```python
def parse(self, text: str, entity: EntityType) -> ReceiptNormalized:
    # Validate we got the right vendor
    if not self.detect_format(text):
        logger.warning("parser_vendor_mismatch",
                      parser=self.__class__.__name__,
                      message="Receipt doesn't match expected vendor format")
    # ... continue parsing
```

---

## Migration Plan

### Phase 1: Textract-Only (Immediate - Low Risk)
- [ ] Update `ocr_receipt.py` task to always use Textract for images
- [ ] Keep Tesseract installed for PDF text extraction fallback
- [ ] Update CLAUDE.md with new policy
- [ ] Update test scripts to use Textract by default

**Estimated effort:** 1-2 hours
**Risk:** Low (Textract already working)

### Phase 2: Vendor Identification (Medium Risk - Requires Testing)
- [ ] Create `vendor_registry.py` with vendor patterns
- [ ] Implement `VendorIdentifier` service
- [ ] Update `VendorDispatcher` to use identifier
- [ ] Test with golden receipts from each vendor
- [ ] Update parsers to remove/deprecate `detect_format()`
- [ ] Update tests to reflect new architecture

**Estimated effort:** 4-6 hours
**Risk:** Medium (requires testing all vendor parsers)

### Phase 3: Parser Cleanup (Low Priority)
- [ ] Remove UPC-based detection from Pepsi parser
- [ ] Remove product-based detection from all parsers
- [ ] Simplify parser detection to name/address only
- [ ] Document vendor pattern discovery process

**Estimated effort:** 2-3 hours
**Risk:** Low (cleanup only)

---

## Handling Multi-Location Vendors

### Problem
- You visit Walmart in Amherst (902-661-3476) and Dartmouth (different phone)
- Same vendor, different receipts look slightly different
- Name might vary: "WALMART", "Walmart Supercenter", "WAL*MART"

### Solution: Location-Agnostic Pattern Matching

**Use ONLY patterns that are consistent across ALL locations:**

1. **Corporate Tax ID (Best)**
   - GST/HST registration number is corporate-wide
   - Example: Walmart = 137466199, Costco = 10846 0400
   - Same number on receipts from ANY location
   - Score: 7 points (high confidence)

2. **Receipt Format Markers (Good)**
   - Walmart: "TC#" + digits
   - Costco: "MEMBER #"
   - Pepsi: "ROUTE #" + "INVOICE #"
   - Same format at all locations
   - Score: 5 points

3. **Vendor Name Variations (Required)**
   - Match multiple variations: `WALMART`, `WAL-MART`, `WALMART SUPERCENTRE`
   - Case-insensitive matching
   - Handles OCR errors (WAL*MART, WAL MART)
   - Score: 10 points (required)

4. **Slogans (Optional Boost)**
   - Walmart: "SAVE MONEY LIVE BETTER"
   - Same across all locations
   - Score: 3 points

**NEVER use:**
- ❌ Street addresses (varies by location)
- ❌ Phone numbers (varies by location)
- ❌ Store numbers (unique per location)

### Example: Walmart Dartmouth vs Amherst

**Amherst Receipt:**
```
WALMART SUPERCENTRE
46 ROBERT ANGUS DR
AMHERST, NS B4H 4R7
902-661-3476
TC# 7087 6751 3781 3481
GST/HST 137466199
```
**Score:** Name(10) + TC#(5) + GST(7) = **22 points** ✅

**Dartmouth Receipt:**
```
WALMART
650 PORTLAND ST
DARTMOUTH, NS B2W 6A3
902-469-3000
TC# 1234 5678 9012 3456
GST/HST 137466199
```
**Score:** Name(10) + TC#(5) + GST(7) = **22 points** ✅

Both identified as `walmart` despite different locations!

---

## Benefits

### Textract-Only
- ✅ Eliminates OCR errors causing false review tasks
- ✅ Reduces AI categorization waste on garbage data
- ✅ Predictable costs (~$0.0015/receipt)
- ✅ No more "confidence threshold" guessing games

### Vendor Name-Based Detection
- ✅ **Eliminates false positives** (no more Walmart → Pepsi mismatches)
- ✅ **Faster detection** (name in header vs scanning all products)
- ✅ **More maintainable** (vendor patterns in one place, not scattered)
- ✅ **Works for all vendors** (every receipt has a name, not every receipt has unique UPCs)
- ✅ **Enables better error messages** ("Identified as Walmart but Costco parser failed" vs generic errors)

---

## Rollout Strategy

1. **Immediate:** Switch to Textract-only (prevents more bad data)
2. **This Week:** Implement vendor identification system
3. **Next Week:** Test with all existing golden receipts
4. **Following Week:** Deploy and monitor for misidentifications

---

## Cost Analysis

### Current State (Tesseract + Manual Review)
- Tesseract: Free
- Manual review of OCR errors: 3 min/receipt × $30/hr = **$1.50/receipt**
- AI categorization on bad data: $0.02 wasted/receipt
- **Total cost per bad receipt: ~$1.52**

### New State (Textract Only)
- Textract: $0.0015/page
- Reduced manual review: 0.5 min/receipt × $30/hr = **$0.25/receipt**
- AI categorization on good data: $0.02 useful/receipt
- **Total cost per receipt: ~$0.27**

**Savings: $1.25 per receipt** (83% reduction in total cost)

For 500 receipts/year: **$625/year saved** while paying **$0.75/year** more for Textract.

**ROI: 833:1**

---

## Open Questions

1. Should we keep Tesseract for local development/testing? (YES - with warnings)
2. What confidence threshold should trigger manual review? (Textract >95% = auto-process)
3. How to handle receipts with no clear vendor name? (Generic parser + human review)
4. Should we validate parser match against vendor identification? (YES - log warnings)

---

## Approval Required

**Decision Maker:** Clarence (Owner)
**Recommendation:** Approve both changes immediately

**Next Steps:**
1. Confirm approval
2. Start Phase 1 (Textract-only) today
3. Begin Phase 2 (Vendor identification) implementation
