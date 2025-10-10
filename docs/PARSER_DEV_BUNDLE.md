# Receipt Parser Development Bundle

This bundle contains the minimal files needed to develop vendor-specific receipt parsers using ChatGPT or other AI tools.

## Files Included

1. **receipt_normalized.py** - Core data schemas (ReceiptNormalized, ReceiptLine, enums)
2. **base_parser.py** - Abstract base class with utility methods
3. **example_parser.py** - Complete working example (Pharmasave parser)

## Usage

To build a new parser:

1. **Study the example parser** - See how Pharmasave parser works
2. **Inherit from BaseReceiptParser** - Implement `detect_format()` and `parse()`
3. **Use provided utilities**:
   - `normalize_price()` - Clean OCR price errors
   - `extract_amount()` - Extract monetary amounts with regex
   - `clean_description()` - Clean item descriptions
   - `handle_missing_line_items()` - Handle faded thermal receipts
4. **Return ReceiptNormalized** - Ensure all required fields are populated
5. **Test with sample receipts** - Verify totals validate correctly

## Key Principles

- **Totals must validate**: `subtotal + tax_total = total` (±$0.02)
- **Line items must sum**: ITEM + FEE lines should sum to subtotal
- **Use Decimal, not float**: All amounts must be `Decimal` type
- **Tax flags matter**: Y (taxable), Z (zero-rated), N (exempt)
- **Handle faded receipts**: Use `handle_missing_line_items()` for thermal receipt fade

## Example Workflow with ChatGPT

```
Prompt: "I have a receipt from [Vendor Name]. Help me build a parser.

The receipt format is:
[paste OCR text or describe format]

Key patterns:
- Header: [vendor identifier]
- Date format: [format]
- Line items: [format]
- Totals: [format]

Here's the base_parser.py and receipt_normalized.py for reference:
[paste files]

Can you help me build a parser that inherits from BaseReceiptParser?"
```

## Testing Your Parser

```python
# Test detection
text = "your OCR text here"
parser = YourParser()
assert parser.detect_format(text) == True

# Test parsing
receipt = parser.parse(text, entity=EntityType.CORP)
assert receipt.total == receipt.subtotal + receipt.tax_total
print(f"Parsed {len(receipt.lines)} lines, total: ${receipt.total}")
```

---

Files below:


═══════════════════════════════════════════════════════════════════════════════
FILE 1: receipt_normalized.py
═══════════════════════════════════════════════════════════════════════════════

"""
Receipt normalized schema (Pydantic models)
Versioned schema for receipt data interchange
"""
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator


class EntityType(str, Enum):
    """Business entity type"""
    CORP = "corp"
    SOLEPROP = "soleprop"


class ReceiptSource(str, Enum):
    """Source of receipt upload"""
    PWA = "pwa"
    EMAIL = "email"
    DRIVE = "drive"
    MANUAL = "manual"


class ReceiptStatus(str, Enum):
    """Receipt processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    POSTED = "posted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class LineType(str, Enum):
    """Type of line item on receipt"""
    ITEM = "item"
    DISCOUNT = "discount"
    DEPOSIT = "deposit"
    FEE = "fee"
    SUBTOTAL = "subtotal"
    TAX = "tax"
    TOTAL = "total"


class TaxFlag(str, Enum):
    """Tax treatment flag"""
    TAXABLE = "Y"
    ZERO_RATED = "Z"
    EXEMPT = "N"


class ReceiptLine(BaseModel):
    """Single line item on a receipt"""
    line_index: int = Field(..., description="Position in receipt (0-based)")
    line_type: LineType
    raw_text: Optional[str] = Field(None, description="Original OCR text")
    
    # Product identification
    vendor_sku: Optional[str] = Field(None, description="Vendor's SKU/product code")
    upc: Optional[str] = Field(None, description="UPC/barcode if available")
    item_description: Optional[str] = Field(None, description="Human-readable description")
    
    # Quantities and pricing
    quantity: Optional[Decimal] = Field(None, ge=0, description="Quantity purchased")
    unit_price: Optional[Decimal] = Field(None, description="Price per unit")
    line_total: Decimal = Field(..., description="Total for this line")
    
    # Tax information
    tax_flag: Optional[TaxFlag] = Field(None, description="Y=taxable, Z=zero-rated, N=exempt")
    tax_amount: Optional[Decimal] = Field(None, ge=0, description="Tax on this line")
    
    # Mapped GL account (filled by classification engine)
    account_code: Optional[str] = Field(None, description="GL account code")
    
    class Config:
        json_schema_extra = {
            "example": {
                "line_index": 0,
                "line_type": "item",
                "raw_text": "PEPSI 24PK 355ML",
                "vendor_sku": "12345678",
                "item_description": "Pepsi 24-pack 355mL",
                "quantity": 2,
                "unit_price": 8.99,
                "line_total": 17.98,
                "tax_flag": "Y",
                "tax_amount": 2.52,
                "account_code": "5010"
            }
        }


class ReceiptNormalized(BaseModel):
    """
    Normalized receipt data structure (version 1)
    This is the canonical format for all receipts after OCR/parsing
    """
    schema_version: str = Field(default="1.0", description="Schema version for compatibility")
    
    # Identifiers
    receipt_id: Optional[UUID] = Field(None, description="System-generated receipt ID")
    entity: EntityType
    source: ReceiptSource
    
    # Vendor information
    vendor_guess: Optional[str] = Field(None, description="Best guess at vendor name")
    vendor_id: Optional[UUID] = Field(None, description="Matched vendor ID from database")
    
    # Receipt metadata
    purchase_date: date = Field(..., description="Date of purchase")
    invoice_number: Optional[str] = Field(None, description="Vendor invoice/receipt number")
    due_date: Optional[date] = Field(None, description="Payment due date (for bills)")
    
    # Amounts
    currency: str = Field(default="CAD", description="Currency code")
    subtotal: Decimal = Field(..., ge=0, description="Subtotal before tax")
    tax_total: Decimal = Field(default=Decimal(0), ge=0, description="Total tax amount")
    total: Decimal = Field(..., ge=0, description="Grand total")
    
    # Line items
    lines: List[ReceiptLine] = Field(default_factory=list, description="Individual line items")
    
    # Classification hints
    is_bill: bool = Field(default=False, description="True if this is a bill (A/P), False if expense")
    payment_terms: Optional[str] = Field(None, description="e.g., Net 7, Net 14")
    
    # Parsing metadata
    ocr_confidence: Optional[int] = Field(None, ge=0, le=100, description="OCR confidence score")
    ocr_method: Optional[str] = Field(None, description="tesseract, gpt4v, manual")
    parsing_errors: Optional[List[str]] = Field(default=None, description="Any parsing issues")
    
    # File references
    content_hash: Optional[str] = Field(None, description="SHA256 hash of original file")
    perceptual_hash: Optional[str] = Field(None, description="Perceptual hash for similarity")
    
    @validator("total")
    def validate_total(cls, v, values):
        """Ensure total matches subtotal + tax"""
        if "subtotal" in values and "tax_total" in values:
            expected_total = values["subtotal"] + values["tax_total"]
            # Allow small rounding differences (up to 2 cents)
            if abs(v - expected_total) > Decimal("0.02"):
                raise ValueError(
                    f"Total ${v} does not match subtotal ${values['subtotal']} + "
                    f"tax ${values['tax_total']} = ${expected_total}"
                )
        return v
    
    @validator("lines")
    def validate_lines_sum(cls, v, values):
        """Ensure line items sum to subtotal"""
        if not v or "subtotal" not in values:
            return v
        
        items_total = sum(
            line.line_total for line in v 
            if line.line_type in [LineType.ITEM, LineType.FEE]
        )
        discounts_total = sum(
            line.line_total for line in v 
            if line.line_type == LineType.DISCOUNT
        )
        
        calculated_subtotal = items_total - abs(discounts_total)
        
        # Allow small rounding differences
        if abs(calculated_subtotal - values["subtotal"]) > Decimal("0.02"):
            raise ValueError(
                f"Line items sum to ${calculated_subtotal} but subtotal is ${values['subtotal']}"
            )
        
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "schema_version": "1.0",
                "entity": "corp",
                "source": "pwa",
                "vendor_guess": "Costco Wholesale",
                "purchase_date": "2025-01-15",
                "currency": "CAD",
                "subtotal": 156.78,
                "tax_total": 21.95,
                "total": 178.73,
                "lines": [
                    {
                        "line_index": 0,
                        "line_type": "item",
                        "vendor_sku": "1234567",
                        "item_description": "Kirkland Paper Towels 12pk",
                        "quantity": 1,
                        "unit_price": 24.99,
                        "line_total": 24.99,
                        "tax_flag": "Y",
                        "tax_amount": 3.50
                    }
                ],
                "ocr_confidence": 92,
                "ocr_method": "tesseract"
            }
        }


class ReceiptUploadResponse(BaseModel):
    """Response after receipt upload"""
    receipt_id: str
    status: ReceiptStatus
    message: str
    task_id: Optional[str] = Field(None, description="Celery task ID for tracking")


class ReceiptReviewRequest(BaseModel):
    """Request to update receipt after review"""
    approved: bool
    corrections: Optional[ReceiptNormalized] = None
    notes: Optional[str] = None
═══════════════════════════════════════════════════════════════════════════════
FILE 2: base_parser.py
═══════════════════════════════════════════════════════════════════════════════

"""
Base Parser - Abstract base class for vendor-specific receipt/invoice parsers

All vendor parsers inherit from BaseReceiptParser and implement:
1. detect_format() - Can this parser handle this text?
2. parse() - Extract data and return ReceiptNormalized

This ensures consistent interface and allows vendor_dispatcher to route receipts.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional
import re

import structlog

from packages.common.schemas.receipt_normalized import (
    ReceiptNormalized,
    ReceiptLine,
    EntityType,
    LineType,
    TaxFlag,
)

logger = structlog.get_logger()


class BaseReceiptParser(ABC):
    """
    Abstract base class for vendor-specific parsers.

    All parsers must implement:
    - detect_format(): Returns True if this parser can handle the text
    - parse(): Extracts data and returns ReceiptNormalized object

    Utility methods provided:
    - normalize_price(): Clean up OCR price errors
    - extract_amount(): Extract decimal amount from text
    """

    @abstractmethod
    def detect_format(self, text: str) -> bool:
        """
        Check if this parser can handle this receipt/invoice.

        Should look for vendor-specific markers like:
        - Vendor name in header
        - Unique SKU patterns
        - Specific layout characteristics

        Args:
            text: Raw OCR text from receipt

        Returns:
            True if this parser can handle this format
        """
        pass

    @abstractmethod
    def parse(self, text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
        """
        Parse receipt text and extract structured data.

        Args:
            text: Raw OCR text from receipt/invoice
            entity: Entity type (corp or soleprop)

        Returns:
            ReceiptNormalized object with extracted data

        Raises:
            ValueError: If required fields cannot be extracted
        """
        pass

    # Utility methods for common parsing tasks

    def normalize_price(self, price_str: str) -> Decimal:
        """
        Clean up OCR price errors and convert to Decimal.

        Common OCR errors:
        - "9.9E" → "9.99" (E instead of 9)
        - "10.0O" → "10.00" (O instead of 0)
        - "$19.99" → "19.99" (remove currency)
        - "1,234.56" → "1234.56" (remove commas)

        Args:
            price_str: Price string from OCR

        Returns:
            Decimal amount

        Raises:
            ValueError: If price cannot be parsed
        """
        # Remove currency symbols and whitespace
        price_str = price_str.strip().replace('$', '').replace(',', '')

        # Fix common OCR errors
        price_str = price_str.replace('E', '9').replace('O', '0').replace('o', '0')

        # Handle negative signs
        is_negative = '-' in price_str or '(' in price_str
        price_str = price_str.replace('-', '').replace('(', '').replace(')', '')

        try:
            amount = Decimal(price_str)
            return -amount if is_negative else amount
        except Exception as e:
            logger.warning("price_parse_failed", price_str=price_str, error=str(e))
            raise ValueError(f"Could not parse price: {price_str}")

    def extract_amount(self, text: str, pattern: str, group: int = 1) -> Optional[Decimal]:
        """
        Extract a monetary amount using regex pattern.

        Args:
            text: Text to search
            pattern: Regex pattern with capturing group for amount
            group: Which capture group contains the amount (default 1)

        Returns:
            Decimal amount or None if not found
        """
        match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
        if match:
            try:
                return self.normalize_price(match.group(group))
            except ValueError:
                return None
        return None

    def clean_description(self, description: str) -> str:
        """
        Clean up item description from OCR artifacts.

        Removes:
        - Extra whitespace
        - Common OCR garbage characters
        - Multiple spaces collapsed to single space

        Args:
            description: Raw description from OCR

        Returns:
            Cleaned description
        """
        # Remove extra whitespace
        description = ' '.join(description.split())

        # Remove common OCR artifacts
        description = description.replace('|', 'I')  # Vertical bar to I
        description = description.replace('_', '')    # Underscores

        return description.strip()

    def detect_vendor_in_text(self, text: str, vendor_patterns: list[str]) -> bool:
        """
        Check if any vendor pattern appears in text.

        Args:
            text: OCR text to search
            vendor_patterns: List of regex patterns or literal strings

        Returns:
            True if any pattern matches
        """
        text_upper = text.upper()
        for pattern in vendor_patterns:
            if re.search(pattern, text_upper):
                return True
        return False

    def handle_missing_line_items(
        self,
        lines: list[ReceiptLine],
        subtotal: Decimal,
        tolerance: Decimal = Decimal('0.10'),
        vendor_name: Optional[str] = None
    ) -> list[ReceiptLine]:
        """
        Handle faded/missing line items by creating placeholder for difference.

        Thermal receipts fade over time, making some line items unreadable.
        When line items don't sum to subtotal (beyond tolerance), create a
        placeholder line item for the missing amount.

        This ensures totals always validate while allowing user to fix details
        in the frontend.

        Args:
            lines: List of extracted line items
            subtotal: Receipt subtotal (from footer)
            tolerance: Maximum acceptable difference (default $0.10)
            vendor_name: Vendor name for logging (optional)

        Returns:
            Updated list of lines (may include placeholder)
        """
        # Sum ITEM and FEE line types (both contribute to subtotal)
        # ITEM = products (COGS), FEE = deposits/environmental charges
        # Exclude DISCOUNT, TAX, etc.
        line_item_total = sum(
            line.line_total for line in lines
            if line.line_type in [LineType.ITEM, LineType.FEE]
        )

        missing_amount = subtotal - line_item_total

        if abs(missing_amount) > tolerance:
            logger.warning(
                "missing_line_items_detected",
                vendor=vendor_name,
                line_item_total=float(line_item_total),
                subtotal=float(subtotal),
                missing=float(missing_amount),
                message="Creating placeholder for unscanned items"
            )

            # Add placeholder line for missing amount
            lines.append(ReceiptLine(
                line_index=len(lines),
                line_type=LineType.ITEM,
                item_description="[Faded/Unscanned Items - Review Required]",
                quantity=Decimal('1'),
                unit_price=missing_amount,
                line_total=missing_amount,
                tax_flag=TaxFlag.TAXABLE,  # Assume taxable (user can adjust)
            ))

            logger.info(
                "placeholder_created",
                vendor=vendor_name,
                placeholder_amount=float(missing_amount)
            )

        return lines


class ParserNotApplicableError(Exception):
    """Raised when a parser's detect_format() returns False but parse() was called anyway"""
    pass


class ParserExtractionError(Exception):
    """Raised when a parser cannot extract required fields from text"""
    pass

═══════════════════════════════════════════════════════════════════════════════
FILE 3: example_parser.py (Pharmasave - Complete Working Example)
═══════════════════════════════════════════════════════════════════════════════

"""
Pharmasave Parser - Handles MacQuarries Pharmasave Amherst receipts

Format:
- Header: "MacQUARRIES PHARMASAVE"
- Customer info section
- Line items with QTY, ITEM #, DESCRIPTION, AMOUNT
- Includes HST and deposit lines
- Air Miles rewards info
- Total discount shown at bottom

Vendor: MacQuarries Pharmasave Amherst
Location: 158 Robert Angus Dr, Amherst, NS B4H 4R7
HST#: 865378210
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Optional

import structlog

from packages.common.schemas.receipt_normalized import (
    ReceiptNormalized,
    ReceiptLine,
    EntityType,
    LineType,
    TaxFlag,
    ReceiptSource,
)
from packages.parsers.vendors.base_parser import BaseReceiptParser

logger = structlog.get_logger()


class PharmasaveParser(BaseReceiptParser):
    """
    Parser for MacQuarries Pharmasave Amherst receipts.

    Handles grocery items, beverages, deposits, and pharmacy items.
    """

    def detect_format(self, text: str) -> bool:
        """
        Detect if this is a Pharmasave receipt.

        Args:
            text: OCR text from receipt

        Returns:
            True if this appears to be a Pharmasave receipt
        """
        text_upper = text.upper()

        # Look for Pharmasave indicators
        pharmasave_indicators = [
            r'MACQUARRIES\s+PHARMASAVE',
            r'PHARMASAVE\s+AMHERST',
            r'158\s+ROBERT\s+ANGUS',
            r'HST\s+NO.*865378210',
        ]

        for pattern in pharmasave_indicators:
            if re.search(pattern, text_upper):
                logger.info("pharmasave_format_detected", pattern=pattern)
                return True

        return False

    def parse(self, text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
        """
        Parse Pharmasave receipt and extract structured data.

        Args:
            text: OCR text from receipt
            entity: Entity type (default: CORP for Curly's Canteen)

        Returns:
            ReceiptNormalized with vendor, date, total, and line items

        Raises:
            ValueError: If required fields cannot be extracted
        """
        logger.info("pharmasave_parsing_started")

        # Extract receipt number
        receipt_match = re.search(r'Receipt:\s*([A-Z0-9]+)', text, re.IGNORECASE)
        receipt_number = receipt_match.group(1) if receipt_match else None

        # Extract date - format: "Date: Sat Oct 04, 2025, 2:56:55 PM"
        date_match = re.search(r'Date:\s*\w+\s+(\w+)\s+(\d{1,2}),\s+(\d{4})', text, re.IGNORECASE)
        date = None
        if date_match:
            try:
                month_str = date_match.group(1)
                day = int(date_match.group(2))
                year = int(date_match.group(3))
                # Parse month name
                date = datetime.strptime(f"{month_str} {day} {year}", '%b %d %Y').date()
            except ValueError:
                logger.warning("date_parse_failed", date_str=date_match.group(0))

        # Extract total - "TOTAL $92.96" (NOT "SUB TOTAL")
        total_match = re.search(r'(?<!SUB\s)TOTAL\s+\$([0-9,.]+)', text, re.IGNORECASE)
        total = self.normalize_price(total_match.group(1)) if total_match else Decimal('0')

        # Extract subtotal - "SUB TOTAL 89.42"
        subtotal_match = re.search(r'SUB\s+TOTAL\s+([0-9,.]+)', text, re.IGNORECASE)
        subtotal = self.normalize_price(subtotal_match.group(1)) if subtotal_match else Decimal('0')

        # Extract HST - "HST (865378210) 3.54"
        hst_match = re.search(r'HST\s*\([0-9]+\)\s+([0-9,.]+)', text, re.IGNORECASE)
        hst = self.normalize_price(hst_match.group(1)) if hst_match else Decimal('0')

        # Extract line items
        lines = self._extract_line_items(text)

        # Handle faded/missing line items (thermal receipt fade is common)
        lines = self.handle_missing_line_items(
            lines=lines,
            subtotal=subtotal,
            vendor_name="MacQuarries Pharmasave"
        )

        logger.info("pharmasave_parsed",
                   receipt=receipt_number,
                   date=str(date),
                   total=float(total),
                   subtotal=float(subtotal),
                   hst=float(hst),
                   lines=len(lines))

        return ReceiptNormalized(
            entity=entity,
            source=ReceiptSource.MANUAL,  # Will be updated by upload handler
            vendor_guess="MacQuarries Pharmasave",
            purchase_date=date or datetime.now().date(),
            invoice_number=receipt_number,
            total=total,
            subtotal=subtotal,
            tax_total=hst,
            lines=lines,
            is_bill=False,  # Pharmasave receipts are A/R (purchases)
            metadata={
                'hst_number': '865378210',
                'branch': '29',
                'location': 'Amherst',
            }
        )

    def _extract_line_items(self, text: str) -> list[ReceiptLine]:
        """
        Extract line items from Pharmasave receipt.

        Format 1 (with quantity):
        QTY  ITEM #    DESCRIPTION           AMOUNT
        1    10035     SCOTSBURN COFFEE      5.05EN
        1    267219    SCOTSBURN 2% MILK 2L  4.19EN

        Format 2 (without quantity - faded receipts):
        ITEM #  DESCRIPTION              AMOUNT
        1004921 WALL TAP                 2.30TN
        996749  SWIFFER STARTER KIT      28.96 TN

        Tax flags: EN = HST exempt/zero-rated, TN = HST taxable, TY = ?

        Deposits are tracked as separate FEE line items since they're expenses
        but not COGS (cost of goods sold).
        """
        lines = []

        # Pattern 1: With quantity (full format)
        # Format: QTY ITEM# DESCRIPTION AMOUNT(with tax flag)
        # Example: "1    10035     SCOTSBURN COFFEE      5.05EN"
        pattern1 = r'^\s*(\d+)\s+(\d{5,})\s+(.+?)\s+([0-9.]+)\s*(EN|TN|TY)\s*$'

        # Pattern 2: Without quantity (faded format)
        # Format: ITEM# DESCRIPTION AMOUNT(with tax flag)
        # Example: "1004921 WALL TAP            2.30TN"
        pattern2 = r'^\s*(\d{5,})\s+(.+?)\s+([0-9.]+)\s*(EN|TN|TY)\s*$'

        # Try pattern 1 first (with quantity)
        for match in re.finditer(pattern1, text, re.MULTILINE):
            quantity = int(match.group(1))
            item_number = match.group(2)
            description = match.group(3).strip()
            amount = Decimal(match.group(4))
            tax_flag_str = match.group(5)

            # Determine tax flag
            if tax_flag_str == 'TN' or tax_flag_str == 'TY':
                tax_flag = TaxFlag.TAXABLE  # HST applicable
            else:  # EN
                tax_flag = TaxFlag.ZERO_RATED  # Zero-rated (groceries)

            # Deposits are FEE line items, not ITEM line items
            is_deposit = 'DEPOSIT' in description.upper()
            line_type = LineType.FEE if is_deposit else LineType.ITEM

            lines.append(ReceiptLine(
                line_index=len(lines),
                line_type=line_type,
                vendor_sku=item_number,
                item_description=self.clean_description(description),
                quantity=Decimal(str(quantity)),
                unit_price=amount,  # Pharmasave shows line total, not unit price
                line_total=amount,
                tax_flag=tax_flag,
            ))

        # If no matches with pattern 1, try pattern 2 (without quantity)
        if len(lines) == 0:
            for match in re.finditer(pattern2, text, re.MULTILINE):
                item_number = match.group(1)
                description = match.group(2).strip()
                amount = Decimal(match.group(3))
                tax_flag_str = match.group(4)

                # Determine tax flag
                if tax_flag_str == 'TN' or tax_flag_str == 'TY':
                    tax_flag = TaxFlag.TAXABLE  # HST applicable
                else:  # EN
                    tax_flag = TaxFlag.ZERO_RATED  # Zero-rated (groceries)

                # Deposits are FEE line items, not ITEM line items
                is_deposit = 'DEPOSIT' in description.upper()
                line_type = LineType.FEE if is_deposit else LineType.ITEM

                # Default quantity to 1 when not specified
                lines.append(ReceiptLine(
                    line_index=len(lines),
                    line_type=line_type,
                    vendor_sku=item_number,
                    item_description=self.clean_description(description),
                    quantity=Decimal('1'),  # Assume 1 when quantity not shown
                    unit_price=amount,
                    line_total=amount,
                    tax_flag=tax_flag,
                ))

        logger.info("pharmasave_lines_extracted", count=len(lines))
        return lines

═══════════════════════════════════════════════════════════════════════════════
END OF BUNDLE
═══════════════════════════════════════════════════════════════════════════════
