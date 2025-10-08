# Vendor-Specific Parsers

This directory contains vendor-specific parsers for receipt and invoice processing.

**Architecture:** All parsers inherit from `BaseReceiptParser` and implement:
- `detect_format(text)` - Returns True if parser can handle this receipt
- `parse(text, entity)` - Extracts data and returns `ReceiptNormalized`

**Dispatcher:** `vendor_dispatcher.py` automatically routes receipts to correct parser.

## Implemented Parsers

### 1. **GFS Canada** (`gfs_parser.py`)
- **Spend:** $40,619.82/year
- **Entity:** Corp (Canteen)
- **Format:** PDF invoices with tabular line items
- **Features:**
  - Multi-page support
  - 7-digit SKU codes
  - Category classification (GR, FR, DY, DS)
  - Pack size parsing (e.g., "2x3.78 L")
  - Fuel surcharges
  - HST calculation (15% on items marked 'H')
- **Payment Terms:** Net 14 (Due Friday)
- **Samples:** 13 invoices

### 2. **Costco Wholesale** (`costco_parser.py`)
- **Spend:** $47,431.07/year
- **Entity:** Both (Corp and Sole Prop)
- **Format:** Online order history PDFs
- **Features:**
  - 6-7 digit SKU codes
  - Tax flags (Y/N) for HST taxable items
  - Container deposit tracking (9484-9495)
  - Instant savings/discounts (TPD codes)
  - Member number tracking
- **Payment:** Immediate (credit card)
- **Samples:** 8 receipts

### 3. **Grosnor Distribution** (`grosnor_parser.py`)
- **Spend:** $65,425.36/year (HIGHEST)
- **Entity:** Sole Prop (Sports store - collectibles)
- **Format:** Professional PDF invoices
- **Features:**
  - Alpha-numeric SKU codes
  - UPC and SRP extraction from descriptions
  - Configuration/pack sizes (e.g., "6/36/10")
  - Freight charges (Canpar shipping)
  - Collectibles-specific (Pokemon, trading cards)
- **Payment Terms:** Credit card or account terms
- **Samples:** 2 invoices

### 4. **Atlantic Superstore** (`superstore_parser.py`)
- **Entity:** Both (Corp and Sole Prop)
- **Format:** Thermal paper receipts
- **Features:**
  - 11-13 digit UPC codes
  - OCR error correction (9.9E → 9.99)
  - Quantity prefixes: (2)UPC = 2 units
  - Brand abbreviations (NN, PC, BM)
  - Tax flag extraction (HMRJ patterns)
- **Payment:** Immediate
- **Special:** Handles poor OCR quality

### 5. **Generic Fallback** (`generic_parser.py`)
- **Format:** Any/Unknown
- **Purpose:** Last resort for unknown vendors or faded receipts
- **Features:**
  - Best-effort total extraction
  - Simple line item patterns
  - Vendor name guessing
  - Multiple date format support
  - All results flagged for manual review
- **Note:** Always returns True from detect_format() (fallback)

## Total Coverage

**Combined Annual Spend:** $153,476.25 (58% of top vendor spend)

## Pending Parsers

### Priority 2 (Next to implement):
1. **Peak Performance** - $21,413.60 (Supplements - Sole Prop)
2. **Fit Foods** - $19,812.78 (Supplements - Sole Prop)
3. **Supplement Facts** - $8,878.43 (Supplements - Sole Prop)
4. **Capital Foodservice** - $8,397.32 (Food - Corp)
5. **Pepsi Bottling** - $6,244.62 (Beverages - Corp)

### Priority 3 (Lower volume):
- Superstore, Pharmasave, Purity Life, Yummy Sports, Believe, Isweet, etc.

## Usage

### Auto-Detection (Recommended)

```python
from packages.parsers.vendor_dispatcher import parse_receipt
from packages.common.schemas.receipt_normalized import EntityType

# Automatically detect vendor and parse
receipt = parse_receipt(ocr_text, entity=EntityType.CORP)
print(f"Vendor: {receipt.vendor_guess}")
print(f"Total: ${receipt.total}")
print(f"Lines: {len(receipt.lines)}")
```

### Manual Parser Selection

```python
from packages.parsers.vendors import (
    parse_gfs_invoice,
    parse_costco_receipt,
    parse_grosnor_invoice,
    parse_superstore_receipt,
    parse_generic_receipt,
)
from packages.common.schemas.receipt_normalized import EntityType

# Parse specific vendor (if you know the format)
gfs_receipt = parse_gfs_invoice(ocr_text, entity=EntityType.CORP)
costco_receipt = parse_costco_receipt(ocr_text, entity=EntityType.CORP)
grosnor_receipt = parse_grosnor_invoice(ocr_text, entity=EntityType.SOLEPROP)
superstore_receipt = parse_superstore_receipt(ocr_text, entity=EntityType.CORP)
generic_receipt = parse_generic_receipt(ocr_text, entity=EntityType.CORP)
```

### Using the Dispatcher Directly

```python
from packages.parsers.vendor_dispatcher import VendorDispatcher

dispatcher = VendorDispatcher()

# Detect vendor without parsing
parser_name = dispatcher.detect_vendor(ocr_text)
print(f"Would use: {parser_name}")

# List all available parsers
parsers = dispatcher.list_parsers()
print(f"Available: {parsers}")

# Parse with dispatcher
receipt = dispatcher.dispatch(ocr_text, entity=EntityType.CORP)
```

## Parser Architecture

Each parser:
1. Extracts metadata (invoice number, date, vendor info)
2. Parses line items with SKUs, descriptions, quantities, prices
3. Calculates tax (HST 15%)
4. Returns `ReceiptNormalized` Pydantic object
5. Includes vendor-specific quirks and validation

All parsers output the same normalized format defined in `packages/common/schemas/receipt_normalized.py`.

## Testing

Golden receipt tests are located in `tests/fixtures/golden_receipts/` with:
- Sample receipt images
- Expected `ReceiptNormalized` JSON output
- Expected `JournalEntry` JSON output

Run tests:
```bash
make test-golden
```

## Adding New Parsers

1. Create `{vendor}_parser.py` in this directory
2. Implement parser class inheriting from base patterns
3. Add convenience function `parse_{vendor}_receipt()`
4. Update `__init__.py` to export new parser
5. Add golden test samples in `tests/fixtures/golden_receipts/{vendor}/`
6. Update this README

## Notes

- All parsers handle HST at 15% (Nova Scotia rate before April 1, 2025)
- Date formats vary by vendor - parsers handle vendor-specific formats
- Some vendors provide UPC codes, others don't
- Account code mapping happens in parsers based on vendor type
