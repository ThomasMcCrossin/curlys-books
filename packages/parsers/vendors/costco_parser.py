"""
Costco Wholesale Receipt Parser

Receipt Format:
- Online order history PDFs (printed from costco.ca)
- Simple line item format: SKU, Description, Price, Tax Flag (Y/N)
- Tax flags: Y = HST taxable, N = Non-taxable
- Includes deposits (container deposits) as separate line items
- Includes instant savings/discounts (TPD codes)
- All items paid together (not a bill, immediate payment)

Key Fields:
- Transaction ID: 12-digit (e.g., 134511170812)
- Date format: MM/DD/YYYY HH:MM
- Member number: 12-digit
- SKU: 6-7 digit item codes
- Deposit codes: 4-digit (9484, 9490, 9491, 9494, 9495, 9488)
- TPD codes: 7-digit discount codes (e.g., 1770709, 1775032)
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


class CostcoParser(BaseReceiptParser):
    """
    Parser for Costco Wholesale receipts.

    Handles:
    - Online order history format
    - Item SKUs and descriptions
    - Tax flags (Y/N)
    - Container deposits
    - Instant savings/discounts (TPD)
    - HST calculation (15%)
    """

    # Deposit item codes (not inventory)
    DEPOSIT_CODES = {'9484', '9485', '9486', '9487', '9488', '9489', '9490', '9491', '9492', '9493', '9494', '9495'}

    # TPD (Temporary Price Discount) codes
    TPD_PATTERN = re.compile(r'TPD/')

    def detect_format(self, text: str) -> bool:
        """
        Detect if this is a Costco receipt.

        Looks for:
        - "Costco" or "COSTCO WHOLESALE" in text
        - Member number pattern
        - Transaction ID pattern
        - Deposit codes (949x)
        """
        text_upper = text.upper()

        # Check for Costco branding
        if any(pattern in text_upper for pattern in [
            'COSTCO WHOLESALE',
            'COSTCO.CA',
            'COSTCO.COM'
        ]):
            return True

        # Check for Costco-specific patterns (member number + transaction ID)
        if re.search(r'Member(?:\s+#)?(?:\s+)?(\d{12})', text, re.IGNORECASE) and \
           re.search(r'Transaction.*?(\d{12})', text, re.IGNORECASE):
            return True

        return False

    def parse(self, text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
        """
        Parse Costco receipt from OCR text.

        Args:
            text: Raw OCR text from PDF
            entity: Entity type (corp or soleprop)

        Returns:
            ReceiptNormalized object
        """
        logger.info("costco_parser_started", entity=entity.value)

        # Extract metadata
        member_number = self._extract_member_number(text)
        transaction_date = self._extract_date(text)
        transaction_id = self._extract_transaction_id(text)

        # Extract line items
        line_items = self._extract_line_items(text)

        # Extract totals
        subtotal = self._extract_subtotal(text)
        tax_total = self._extract_tax(text)
        total = self._extract_total(text)
        instant_savings = self._extract_instant_savings(text)

        # Convert to ReceiptLine objects
        receipt_lines = []
        line_index = 0

        for item in line_items:
            # Skip deposit lines (we'll add them separately if needed)
            if item['sku'] in self.DEPOSIT_CODES:
                continue

            # Check if this is a discount/TPD line
            if self.TPD_PATTERN.search(item['description']):
                line_type = LineType.DISCOUNT
                # Discounts are negative
                line_total = -abs(item['price'])
                tax_flag = TaxFlag.EXEMPT
                tax_amount = Decimal('0')
            else:
                line_type = LineType.ITEM
                line_total = item['price']

                # Determine tax flag
                if item['tax_flag'] == 'Y':
                    tax_flag = TaxFlag.TAXABLE
                    # Calculate tax for this line (15% HST)
                    # Tax is already included in the total tax, but we estimate per-line
                    tax_amount = line_total * Decimal('0.15')
                else:
                    tax_flag = TaxFlag.EXEMPT
                    tax_amount = Decimal('0')

            receipt_lines.append(ReceiptLine(
                line_index=line_index,
                line_type=line_type,
                raw_text=f"{item['sku']} {item['description']}",
                vendor_sku=item['sku'],
                item_description=item['description'],
                quantity=Decimal('1'),  # Costco doesn't show quantity, price is extended
                unit_price=line_total,
                line_total=line_total,
                tax_flag=tax_flag,
                tax_amount=tax_amount,
                account_code='5010',  # COGS - Inventory
            ))
            line_index += 1

        logger.info("costco_parser_completed",
                   transaction_id=transaction_id,
                   lines=len(receipt_lines),
                   total=float(total),
                   instant_savings=float(instant_savings))

        return ReceiptNormalized(
            entity=entity,
            source=ReceiptSource.MANUAL,  # Will be overridden by caller
            vendor_guess="Costco Wholesale",
            purchase_date=transaction_date,
            invoice_number=transaction_id,
            currency="CAD",
            subtotal=subtotal,
            tax_total=tax_total,
            total=total,
            lines=receipt_lines,
            is_bill=False,  # Costco is paid immediately
            ocr_method="costco_parser",
            ocr_confidence=95,
            parsing_errors=[f"Instant savings: ${instant_savings}"] if instant_savings > 0 else None,
        )

    def _extract_member_number(self, text: str) -> Optional[str]:
        """Extract Costco member number"""
        match = re.search(r'Member\s+(\d{12})', text)
        if match:
            return match.group(1)
        return None

    def _extract_date(self, text: str) -> datetime.date:
        """
        Extract transaction date.
        Format: MM/DD/YYYY HH:MM followed by transaction ID
        Example: "09/08/2023 12:57 13451117081"
        """
        # Look for date at the bottom with transaction ID
        match = re.search(r'(\d{2}/\d{2}/\d{4})\s+\d{2}:\d{2}\s+\d{11,12}', text)
        if match:
            return datetime.strptime(match.group(1), '%m/%d/%Y').date()

        # Fallback: look for date in format "P7 MM/DD/YYYY"
        match = re.search(r'P7\s+(\d{2}/\d{2}/\d{4})', text)
        if match:
            return datetime.strptime(match.group(1), '%m/%d/%Y').date()

        raise ValueError("Could not extract transaction date")

    def _extract_transaction_id(self, text: str) -> str:
        """
        Extract transaction ID (11-12 digits after date/time)
        Example: "09/08/2023 12:57 13451117081"
        """
        match = re.search(r'\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\s+(\d{11,12})', text)
        if match:
            return match.group(1)

        # Fallback: try to extract from barcode number (longer format)
        match = re.search(r'(\d{23})', text)
        if match:
            return match.group(1)

        return "UNKNOWN"

    def _extract_line_items(self, text: str) -> List[dict]:
        """
        Extract line items from receipt.

        Format:
        SKU DESCRIPTION PRICE [TAX_FLAG]

        Examples:
        306657 GATORADE 65.97 Y
        1510576 OASIS APP G 15.99 N
        9490 DEPOSIT/306 8.40
        1770709 TPD/PEPSI 2.90-
        """
        items = []

        # Pattern for regular items
        # Matches: SKU (4-7 digits) DESCRIPTION PRICE [Y/N]
        pattern = r'(\d{4,7})\s+([A-Z][A-Z\s\*/\-]+?)\s+([\d.]+)(-?)\s*([YN])?(?:\s|$)'

        for match in re.finditer(pattern, text, re.MULTILINE):
            try:
                sku = match.group(1)
                description = match.group(2).strip()
                price_str = match.group(3)
                is_negative = match.group(4) == '-'
                tax_flag = match.group(5) or ''

                # Parse price
                price = Decimal(price_str)
                if is_negative:
                    price = -price

                items.append({
                    'sku': sku,
                    'description': description,
                    'price': price,
                    'tax_flag': tax_flag,
                })
            except (ValueError, IndexError) as e:
                logger.warning("costco_line_parse_failed", error=str(e), line=match.group(0))
                continue

        logger.info("costco_lines_extracted", count=len(items))
        return items

    def _extract_subtotal(self, text: str) -> Decimal:
        """Extract subtotal (before tax)"""
        match = re.search(r'SUBTOTAL\s+([\d,]+\.\d{2})', text)
        if match:
            return Decimal(match.group(1).replace(',', ''))
        return Decimal('0')

    def _extract_tax(self, text: str) -> Decimal:
        """Extract total tax (HST)"""
        # Look for "TAX" line (not "TOTAL TAX")
        match = re.search(r'(?<!TOTAL )TAX\s+([\d,]+\.\d{2})', text)
        if match:
            return Decimal(match.group(1).replace(',', ''))

        # Fallback: look for HST line
        match = re.search(r'\(A\)\s+15%\s+HST\s+([\d,]+\.\d{2})', text)
        if match:
            return Decimal(match.group(1).replace(',', ''))

        return Decimal('0')

    def _extract_total(self, text: str) -> Decimal:
        """Extract total amount"""
        match = re.search(r'\*+\s+TOTAL\s+([\d,]+\.\d{2})', text)
        if match:
            return Decimal(match.group(1).replace(',', ''))
        raise ValueError("Could not extract total")

    def _extract_instant_savings(self, text: str) -> Decimal:
        """Extract instant savings (discounts applied)"""
        match = re.search(r'INSTANT SAVINGS\s+\$?([\d,]+\.\d{2})', text)
        if match:
            return Decimal(match.group(1).replace(',', ''))
        return Decimal('0')


def parse_costco_receipt(text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
    """
    Convenience function to parse Costco receipt.

    Args:
        text: OCR text from Costco receipt PDF
        entity: Entity type (corp or soleprop)

    Returns:
        ReceiptNormalized object
    """
    parser = CostcoParser()
    return parser.parse(text, entity)
