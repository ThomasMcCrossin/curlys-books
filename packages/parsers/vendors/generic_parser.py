"""
Generic Fallback Receipt Parser

Used when no vendor-specific parser matches the receipt format.

Strategy:
- Extract whatever totals are readable (subtotal, tax, total)
- Try to identify line items with simple patterns
- Flag everything for manual review
- Provide best-effort parsing for unknown vendors or faded receipts

This parser never returns False from detect_format() - it's the last resort.
"""

from decimal import Decimal
from datetime import datetime
from typing import List, Optional
import re

import structlog

from packages.common.schemas.receipt_normalized import (
    ReceiptNormalized,
    ReceiptLine,
    LineType,
    TaxFlag,
    EntityType,
    ReceiptSource,
)
from packages.parsers.vendors.base_parser import BaseReceiptParser

logger = structlog.get_logger()


class GenericParser(BaseReceiptParser):
    """
    Generic fallback parser for unknown vendors or poor quality OCR.

    Handles:
    - Basic total extraction
    - Simple line item patterns
    - Vendor name guessing from header
    - Date extraction (multiple formats)
    - HST calculation by reverse-engineering from total

    All results flagged for manual review.
    """

    def detect_format(self, text: str) -> bool:
        """
        Generic parser always returns True - it's the fallback.

        Args:
            text: OCR text

        Returns:
            Always True (last resort)
        """
        return True

    def parse(self, text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
        """
        Best-effort parsing of unknown receipt format.

        Args:
            text: Raw OCR text from receipt
            entity: Entity type (corp or soleprop)

        Returns:
            ReceiptNormalized object with basic data extracted
        """
        logger.info("generic_parser_started", entity=entity.value, text_length=len(text))

        # Try to extract basic metadata
        vendor_guess = self._guess_vendor(text)
        purchase_date = self._extract_date(text)
        invoice_number = self._extract_invoice_number(text)

        # Extract totals (required fields)
        try:
            total = self._extract_total(text)
            tax_total = self._extract_tax(text)
            subtotal = total - tax_total if tax_total else self._extract_subtotal(text)

            # If subtotal missing, calculate from total
            if subtotal == Decimal('0') and total > 0:
                if tax_total > 0:
                    subtotal = total - tax_total
                else:
                    # Assume 15% HST and back-calculate
                    subtotal = total / Decimal('1.15')
                    tax_total = total - subtotal

        except ValueError as e:
            logger.error("generic_parser_totals_failed", error=str(e))
            # Create placeholder values to avoid parsing failure
            total = Decimal('0')
            subtotal = Decimal('0')
            tax_total = Decimal('0')

        # Try to extract line items (best effort)
        line_items = self._extract_line_items(text)

        # Convert to ReceiptLine objects
        receipt_lines = []
        for idx, item in enumerate(line_items):
            receipt_lines.append(ReceiptLine(
                line_index=idx,
                line_type=LineType.ITEM,
                raw_text=item['raw_text'],
                vendor_sku=item.get('sku'),
                item_description=item['description'],
                quantity=item.get('quantity', Decimal('1')),
                unit_price=item.get('unit_price'),
                line_total=item.get('line_total', Decimal('0')),
                tax_flag=TaxFlag.UNKNOWN,  # Can't determine reliably
                account_code='5010',  # Default to inventory
            ))

        logger.warning("generic_parser_completed",
                      vendor=vendor_guess,
                      lines=len(receipt_lines),
                      total=float(total),
                      note="REQUIRES MANUAL REVIEW - Generic parser used")

        return ReceiptNormalized(
            entity=entity,
            source=ReceiptSource.MANUAL,
            vendor_guess=vendor_guess or "UNKNOWN VENDOR",
            purchase_date=purchase_date or datetime.now().date(),
            invoice_number=invoice_number or "UNKNOWN",
            currency="CAD",
            subtotal=subtotal,
            tax_total=tax_total,
            total=total,
            lines=receipt_lines,
            is_bill=False,
            ocr_method="generic_parser",
            ocr_confidence=50,  # Low confidence - generic parser
        )

    def _guess_vendor(self, text: str) -> Optional[str]:
        """
        Try to extract vendor name from receipt header.

        Looks at first 200 characters for company name patterns.
        """
        header = text[:200].upper()

        # Common vendor patterns
        vendor_patterns = [
            r'([A-Z\s&]+(?:INC|LTD|LLC|CORP|CO)\.?)',
            r'([A-Z\s&]{3,})\s+(?:RECEIPT|INVOICE)',
            r'(?:STORE|SHOP|MARKET)[\s:]+([A-Z\s&]+)',
        ]

        for pattern in vendor_patterns:
            match = re.search(pattern, header)
            if match:
                vendor = match.group(1).strip()
                if len(vendor) > 3:  # Sanity check
                    return vendor

        return None

    def _extract_date(self, text: str) -> Optional[datetime.date]:
        """
        Try multiple date formats.

        Returns None if no date found (will use today's date).
        """
        date_patterns = [
            r'(\d{4})[/-](\d{2})[/-](\d{2})',  # YYYY-MM-DD
            r'(\d{2})[/-](\d{2})[/-](\d{4})',  # MM-DD-YYYY or DD-MM-YYYY
            r'(\d{2})[/-](\d{2})[/-](\d{2})',  # YY-MM-DD or MM-DD-YY
        ]

        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    parts = [int(p) for p in match.groups()]

                    # Try to determine format
                    if pattern == date_patterns[0]:  # YYYY-MM-DD
                        return datetime(parts[0], parts[1], parts[2]).date()
                    elif pattern == date_patterns[1]:  # Ambiguous
                        # Assume MM-DD-YYYY if first number <= 12
                        if parts[0] <= 12:
                            return datetime(parts[2], parts[0], parts[1]).date()
                        else:
                            return datetime(parts[2], parts[1], parts[0]).date()
                    elif pattern == date_patterns[2]:  # YY-MM-DD
                        year = parts[0] + 2000 if parts[0] < 50 else parts[0] + 1900
                        return datetime(year, parts[1], parts[2]).date()
                except (ValueError, IndexError):
                    continue

        return None

    def _extract_invoice_number(self, text: str) -> Optional[str]:
        """Extract invoice/receipt number if present"""
        patterns = [
            r'(?:INVOICE|RECEIPT|ORDER)[\s#:]*(\w+)',
            r'#\s*(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _extract_total(self, text: str) -> Decimal:
        """Extract total amount (required)"""
        patterns = [
            r'TOTAL\s+\$?([\d,]+\.?\d{2})',
            r'AMOUNT\s+\$?([\d,]+\.?\d{2})',
            r'BALANCE\s+\$?([\d,]+\.?\d{2})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return self.normalize_price(match.group(1))

        raise ValueError("Could not extract total from receipt")

    def _extract_subtotal(self, text: str) -> Decimal:
        """Extract subtotal if present"""
        match = re.search(r'SUBTOTAL\s+\$?([\d,]+\.?\d{2})', text, re.IGNORECASE)
        if match:
            return self.normalize_price(match.group(1))
        return Decimal('0')

    def _extract_tax(self, text: str) -> Decimal:
        """Extract tax total if present"""
        patterns = [
            r'(?:GST|HST|TAX)\s+\$?([\d,]+\.?\d{2})',
            r'TAX\s+TOTAL\s+\$?([\d,]+\.?\d{2})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return self.normalize_price(match.group(1))

        return Decimal('0')

    def _extract_line_items(self, text: str) -> List[dict]:
        """
        Best-effort extraction of line items.

        Looks for lines with:
        - Optional SKU/item code
        - Description
        - Price at end of line
        """
        items = []

        # Simple pattern: anything followed by a price
        pattern = r'^(.+?)\s+\$?([\d,]+\.?\d{2})\s*$'

        for line in text.split('\n'):
            line = line.strip()
            if len(line) < 5:
                continue

            match = re.match(pattern, line)
            if match:
                description = match.group(1).strip()
                price = self.normalize_price(match.group(2))

                # Skip if it looks like a total line
                if any(keyword in description.upper() for keyword in [
                    'TOTAL', 'SUBTOTAL', 'TAX', 'BALANCE', 'CASH', 'CHANGE'
                ]):
                    continue

                items.append({
                    'description': description,
                    'line_total': price,
                    'raw_text': line,
                })

        logger.info("generic_lines_extracted", count=len(items))
        return items


def parse_generic_receipt(text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
    """
    Convenience function to parse unknown receipt format.

    Args:
        text: OCR text from receipt
        entity: Entity type (corp or soleprop)

    Returns:
        ReceiptNormalized object (flagged for review)
    """
    parser = GenericParser()
    return parser.parse(text, entity)
