# Parser Development Guide

## Quick Answer: What Files Do You Need?

To build parsers with ChatGPT (or any AI tool), you need **3 files**:

1. **`receipt_normalized.py`** - Data schemas (ReceiptNormalized, ReceiptLine, enums)
2. **`base_parser.py`** - Abstract base class with utility methods
3. **`example_parser.py`** - Complete working example (use Pharmasave as template)

📦 **All 3 files bundled together**: `docs/PARSER_DEV_BUNDLE.md`

---

## Development Workflow

### Step 1: Get Sample Receipt
- Take photo of receipt or get OCR text
- Note key patterns: vendor name, date format, line item structure

### Step 2: Prompt ChatGPT
```
I need to build a parser for [Vendor Name] receipts.

Receipt format:
[paste OCR text or describe structure]

Key observations:
- Vendor identifier: [e.g., "COSTCO WHOLESALE"]
- Date format: [e.g., "MM/DD/YY"]
- Line items: [describe pattern]
- Tax handling: [describe]

I have these base files:
[paste receipt_normalized.py]
[paste base_parser.py]

Here's a working example from Pharmasave:
[paste pharmasave_parser.py]

Can you help me build a parser that:
1. Inherits from BaseReceiptParser
2. Implements detect_format() to identify this vendor
3. Implements parse() to extract all fields
4. Uses handle_missing_line_items() for faded receipts
```

### Step 3: Iterate
- Test parser with sample receipts
- Refine regex patterns
- Handle edge cases (multi-page, discounts, deposits)

### Step 4: Validate
```python
# Test detection
assert parser.detect_format(ocr_text) == True

# Test parsing
receipt = parser.parse(ocr_text, entity=EntityType.CORP)

# Verify totals
assert receipt.total == receipt.subtotal + receipt.tax_total
assert abs((receipt.subtotal - sum(l.line_total for l in receipt.lines 
    if l.line_type in [LineType.ITEM, LineType.FEE]))) < 0.02
```

---

## Key Patterns from Pharmasave Example

### 1. detect_format()
```python
def detect_format(self, text: str) -> bool:
    text_upper = text.upper()
    vendor_indicators = [
        r'VENDOR\s+NAME',
        r'UNIQUE\s+PATTERN',
        r'HST\s+NO.*\d+',
    ]
    for pattern in vendor_indicators:
        if re.search(pattern, text_upper):
            return True
    return False
```

### 2. Extract Totals
```python
# Use negative lookbehind to avoid false matches
total_match = re.search(r'(?<!SUB\s)TOTAL\s+\$([0-9,.]+)', text, re.IGNORECASE)
total = self.normalize_price(total_match.group(1)) if total_match else Decimal('0')
```

### 3. Extract Line Items
```python
# Use multiline regex with named groups
pattern = r'^\s*(\d+)\s+(\d{5,})\s+(.+?)\s+([0-9.]+)\s*(EN|TN|TY)\s*$'
for match in re.finditer(pattern, text, re.MULTILINE):
    qty = int(match.group(1))
    sku = match.group(2)
    desc = match.group(3).strip()
    amount = Decimal(match.group(4))
    tax_flag = match.group(5)
    # ... create ReceiptLine
```

### 4. Handle Faded Receipts
```python
# After extracting line items
lines = self._extract_line_items(text)

# Automatically handle missing items
lines = self.handle_missing_line_items(
    lines=lines,
    subtotal=subtotal,
    vendor_name="Vendor Name"
)
```

### 5. Use Utility Methods
```python
# Clean prices
price = self.normalize_price("$19.99")  # Returns Decimal('19.99')

# Extract with regex
amount = self.extract_amount(text, r'TOTAL:\s*\$?([0-9,.]+)')

# Clean descriptions
desc = self.clean_description("  PEPSI   2L  ")  # "PEPSI 2L"
```

---

## Common Receipt Formats

### Grocery/Retail (Pharmasave, Costco, Superstore)
- Line items with: QTY, ITEM#, DESCRIPTION, AMOUNT, TAX_FLAG
- Deposits tracked separately as FEE
- HST shown separately
- Multi-format support needed (clear vs faded)

### Wholesale/Distributor (GFS, Grosnor)
- May have unit price + quantity
- Case/pack quantities
- Different tax rates (HST, provincial)
- Account codes on invoice

### Beverage Distributors (Pepsi, Coke)
- Product codes
- Deposits as separate lines
- Volume discounts
- Delivery fees

---

## Validation Rules

All parsers must satisfy:

1. **Total validation**: `subtotal + tax_total = total` (±$0.02)
2. **Line sum validation**: ITEM + FEE lines sum to subtotal (±$0.02)
3. **Required fields**: vendor_guess, purchase_date, total, subtotal, lines
4. **Decimal precision**: All amounts are `Decimal`, never `float`
5. **Tax flags**: Y (taxable), Z (zero-rated), N (exempt)

---

## Testing Checklist

- [ ] Clear receipt parses correctly
- [ ] Faded receipt gets placeholder for missing items
- [ ] Multi-page receipts handled (if applicable)
- [ ] Deposits tracked as FEE (if applicable)
- [ ] Discounts tracked as DISCOUNT (if applicable)
- [ ] Date extraction works for vendor's format
- [ ] Invoice/receipt number extracted
- [ ] Totals validate (subtotal + tax = total)
- [ ] Line items sum to subtotal
- [ ] Tax flags correctly assigned

---

## Troubleshooting

### Problem: Regex not matching
- Test regex at regex101.com with actual OCR text
- Remember: OCR adds extra whitespace
- Use `\s+` for flexible whitespace matching

### Problem: Totals don't validate
- Check if deposits/fees are included in subtotal
- Verify rounding (use ±$0.02 tolerance)
- Ensure DISCOUNT lines are subtracted

### Problem: Line items include non-items
- Tighten regex patterns
- Add negative lookahead for footer patterns
- Require specific markers (tax flags, item numbers)

### Problem: Faded receipts fail
- Use `handle_missing_line_items()` from base parser
- Consider multiple regex patterns (with/without quantity)
- Test with actual faded receipt samples

---

## Contributing Parsers Back

Once your parser works:

1. Test with 3+ sample receipts (clear, faded, edge cases)
2. Add parser to `packages/parsers/vendors/`
3. Register in `vendor_dispatcher.py`
4. Add golden test fixtures in `tests/fixtures/golden_receipts/`
5. Update this guide with vendor-specific tips

---

## Resources

- **Regex tester**: https://regex101.com (use Python flavor)
- **Pydantic docs**: https://docs.pydantic.dev
- **structlog docs**: https://www.structlog.org
- **Decimal module**: https://docs.python.org/3/library/decimal.html

