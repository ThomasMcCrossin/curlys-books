"""
Atlantic Superstore Receipt Parser

Receipt Format:
- Thermal paper receipts with varying OCR quality
- UPC codes (11-13 digits) for each item
- Brand abbreviations (NN = No Name, PC = President's Choice, etc.)
- Tax flags in description line (HMRJ, MRJ, etc.)
- H = HST taxable, M = Meal replacement (?), R = ?, J = ?

Key Challenges:
- OCR errors: "9.9E" instead of "$9.99" (E substituted for final 9)
- Quantity prefixes: (2)05870322321 means 2 units of that UPC
- Variable spacing between fields
- Sometimes SKU wraps to next line

Pattern Example:
(2)05870322321    NN DRY CLOTH ORI  HMRJ     10.9E
06038318936       NN IC SNDW VAN    HMRJ      9.9E
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


class SuperstoreParser(BaseReceiptParser):
    """
    Parser for Atlantic Superstore receipts.

    Handles:
    - UPC/EAN codes (11-13 digits)
    - OCR price errors (9.9E → 9.99)
    - Quantity prefixes
    - Brand abbreviations
    - Tax flag extraction (HMRJ patterns)
    - HST calculation (15%)
    """

    # Brand abbreviations
    BRAND_CODES = {
        'NN': 'No Name',
        'PC': 'President\'s Choice',
        'BM': 'Blue Menu',
        'SS': 'Superstore',
    }

    def detect_format(self, text: str) -> bool:
        """
        Detect if this is an Atlantic Superstore receipt.

        Looks for:
        - "Atlantic Superstore" or "Superstore" in header
        - Long UPC codes (11-13 digits)
        - Brand codes (NN, PC, etc.)
        - Tax flag patterns (HMRJ, MRJ)
        """
        text_upper = text.upper()

        # Check for Superstore branding
        if any(pattern in text_upper for pattern in [
            'ATLANTIC SUPERSTORE',
            'SUPERSTORE',
            'LOBLAWS',
        ]):
            return True

        # Check for Superstore-specific patterns (long UPCs + tax flags)
        if re.search(r'\d{11,13}\s+(NN|PC|BM)', text) and re.search(r'(H?M?R?J?)', text):
            return True

        return False

    def parse(self, text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
        """
        Parse Atlantic Superstore receipt from OCR text.

        Args:
            text: Raw OCR text from receipt
            entity: Entity type (corp or soleprop)

        Returns:
            ReceiptNormalized object
        """
        logger.info("superstore_parser_started", entity=entity.value)

        # Extract metadata
        purchase_date = self._extract_date(text)
        transaction_number = self._extract_transaction_number(text)

        # Extract line items
        line_items = self._extract_line_items(text)

        # Extract totals
        subtotal = self._extract_subtotal(text)
        tax_total = self._extract_tax(text)
        total = self._extract_total(text)

        # Convert to ReceiptLine objects
        receipt_lines = []
        for idx, item in enumerate(line_items):
            # Determine tax flag from tax code
            tax_flag = TaxFlag.TAXABLE if 'H' in item.get('tax_code', '') else TaxFlag.EXEMPT

            # Calculate line tax if taxable
            line_tax = item['line_total'] * Decimal('0.15') if tax_flag == TaxFlag.TAXABLE else Decimal('0')

            receipt_lines.append(ReceiptLine(
                line_index=idx,
                line_type=LineType.ITEM,
                raw_text=item['raw_text'],
                vendor_sku=item['sku'],
                item_description=item['description'],
                quantity=item['quantity'],
                unit_price=item['unit_price'],
                line_total=item['line_total'],
                tax_flag=tax_flag,
                tax_amount=line_tax,
                account_code='5010',  # COGS - Inventory
            ))

        logger.info("superstore_parser_completed",
                   transaction=transaction_number,
                   lines=len(receipt_lines),
                   total=float(total))

        return ReceiptNormalized(
            entity=entity,
            source=ReceiptSource.MANUAL,
            vendor_guess="Atlantic Superstore",
            purchase_date=purchase_date,
            invoice_number=transaction_number,
            currency="CAD",
            subtotal=subtotal,
            tax_total=tax_total,
            total=total,
            lines=receipt_lines,
            is_bill=False,  # Immediate payment
            ocr_method="superstore_parser",
            ocr_confidence=85,  # Lower due to OCR challenges
        )

    def _extract_date(self, text: str) -> datetime.date:
        """Extract purchase date"""
        # Try YYYY/MM/DD format
        match = re.search(r'(\d{4})[/-](\d{2})[/-](\d{2})', text)
        if match:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))).date()

        # Try MM/DD/YYYY format
        match = re.search(r'(\d{2})[/-](\d{2})[/-](\d{4})', text)
        if match:
            return datetime(int(match.group(3)), int(match.group(1)), int(match.group(2))).date()

        raise ValueError("Could not extract purchase date")

    def _extract_transaction_number(self, text: str) -> str:
        """Extract transaction/register number"""
        match = re.search(r'(?:TRANS|TXN|REG)[\s#:]*(\d+)', text, re.IGNORECASE)
        if match:
            return match.group(1)
        return "UNKNOWN"

    def _extract_line_items(self, text: str) -> List[dict]:
        """
        Extract line items with OCR error correction.

        Pattern: (qty)UPC  BRAND DESCRIPTION  TAXCODE  PRICE
        Example: (2)05870322321    NN DRY CLOTH ORI  HMRJ     10.9E
        """
        items = []

        # Pattern for line items with optional quantity prefix
        pattern = r'(?:\((\d+)\))?\s*(\d{11,13})\s+(.*?)\s+(H?M?R?J?)\s+([\d.]+)([E9]?)\s*$'

        for match in re.finditer(pattern, text, re.MULTILINE):
            try:
                quantity_str = match.group(1) or '1'
                sku = match.group(2)
                description_raw = match.group(3).strip()
                tax_code = match.group(4)
                price_raw = match.group(5)
                price_suffix = match.group(6)

                # Fix OCR price error: "10.9E" → "10.99"
                if price_suffix == 'E':
                    price_raw += '9'
                elif price_suffix == '9':
                    price_raw += '9'  # Already has the 9, just concat

                line_total = Decimal(price_raw)
                quantity = Decimal(quantity_str)
                unit_price = line_total / quantity if quantity > 0 else line_total

                # Clean description
                description = self.clean_description(description_raw)

                items.append({
                    'sku': sku,
                    'description': description,
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'line_total': line_total,
                    'tax_code': tax_code,
                    'raw_text': match.group(0),
                })

            except (ValueError, IndexError) as e:
                logger.warning("superstore_line_parse_failed", error=str(e), line=match.group(0))
                continue

        logger.info("superstore_lines_extracted", count=len(items))
        return items

    def _extract_subtotal(self, text: str) -> Decimal:
        """Extract subtotal before tax"""
        match = re.search(r'SUBTOTAL\s+\$?([\d,]+\.?\d{2})', text, re.IGNORECASE)
        if match:
            return Decimal(match.group(1).replace(',', ''))
        return Decimal('0')

    def _extract_tax(self, text: str) -> Decimal:
        """Extract HST total"""
        match = re.search(r'(?:HST|TAX|GST)\s+\$?([\d,]+\.?\d{2})', text, re.IGNORECASE)
        if match:
            return Decimal(match.group(1).replace(',', ''))
        return Decimal('0')

    def _extract_total(self, text: str) -> Decimal:
        """Extract total amount"""
        match = re.search(r'TOTAL\s+\$?([\d,]+\.?\d{2})', text, re.IGNORECASE)
        if match:
            return Decimal(match.group(1).replace(',', ''))
        raise ValueError("Could not extract total")


def parse_superstore_receipt(text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
    """
    Convenience function to parse Atlantic Superstore receipt.

    Args:
        text: OCR text from Superstore receipt
        entity: Entity type (corp or soleprop)

    Returns:
        ReceiptNormalized object
    """
    parser = SuperstoreParser()
    return parser.parse(text, entity)
