"""
Grosnor Distribution Invoice Parser

Invoice Format:
- Professional PDF invoices for collectibles (Pokemon, trading cards, etc.)
- Detailed line items with SKU, description, SRP, UPC
- Configuration format: (case/inner/unit) e.g., (6/36/10)
- Clean pricing structure with unit prices and extended prices
- Includes freight charges
- GST/HST at 15%
- Payment terms shown (VISA/MC/VDCARD or account terms)

Key Fields:
- Invoice number: 6-digit (e.g., 217427)
- Order number: 6-digit (e.g., 229224)
- Account number: 7-digit (e.g., 6692700)
- Date format: MM/DD/YY
- Item codes: Alpha-numeric SKUs
- Configuration: (case/inner/unit) format
- UOM: EA, BX (Each, Box)
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


class GrosnorParser(BaseReceiptParser):
    """
    Parser for Grosnor Distribution invoices.

    Handles:
    - Collectibles invoices (Pokemon, trading cards)
    - SKU and UPC codes
    - SRP (Suggested Retail Price) in descriptions
    - Configuration/pack sizes
    - Freight charges
    - HST calculation (15%)
    """

    def detect_format(self, text: str) -> bool:
        """
        Detect if this is a Grosnor Distribution invoice.

        Looks for:
        - "Grosnor" or "GROSNOR DISTRIBUTION" in header
        - Configuration format: (6/36/10)
        - UPC codes in descriptions
        - Collectibles keywords (Pokemon, TCG, etc.)
        """
        text_upper = text.upper()

        # Check for Grosnor branding
        if any(pattern in text_upper for pattern in [
            'GROSNOR DISTRIBUTION',
            'GROSNOR.COM',
            'WWW.GROSNOR.COM'
        ]):
            return True

        # Check for Grosnor-specific patterns (configuration format + UPC/SRP)
        if re.search(r'\(\d+/\d+/\d+\)', text) and re.search(r'\(UPC\s+\d+\)', text):
            return True

        return False

    def parse(self, text: str, entity: EntityType = EntityType.SOLEPROP) -> ReceiptNormalized:
        """
        Parse Grosnor invoice from OCR text.

        Args:
            text: Raw OCR text from PDF
            entity: Entity type (typically soleprop for Sports store)

        Returns:
            ReceiptNormalized object
        """
        logger.info("grosnor_parser_started", entity=entity.value)

        # Extract metadata
        invoice_number = self._extract_invoice_number(text)
        order_number = self._extract_order_number(text)
        invoice_date = self._extract_date(text)

        # Extract line items
        line_items = self._extract_line_items(text)

        # Extract totals
        sales_amount = self._extract_sales_amount(text)
        freight = self._extract_freight(text)
        misc = self._extract_misc(text)
        tax_total = self._extract_tax(text)
        total = self._extract_total(text)

        # Convert to ReceiptLine objects
        receipt_lines = []
        line_index = 0

        for item in line_items:
            receipt_lines.append(ReceiptLine(
                line_index=line_index,
                line_type=LineType.ITEM,
                raw_text=f"{item['sku']} {item['description'][:50]}",
                vendor_sku=item['sku'],
                upc=item.get('upc'),
                item_description=item['description'],
                quantity=Decimal(str(item['qty_shipped'])),
                unit_price=item['unit_price'],
                line_total=item['extended_price'],
                tax_flag=TaxFlag.TAXABLE,  # All items are HST taxable
                tax_amount=item['extended_price'] * Decimal('0.15'),
                account_code='5020',  # COGS - Collectibles
            ))
            line_index += 1

        # Add freight as separate line if present
        if freight > 0:
            receipt_lines.append(ReceiptLine(
                line_index=line_index,
                line_type=LineType.FEE,
                raw_text="Freight Charge",
                item_description="Shipping - Canpar",
                quantity=Decimal('1'),
                unit_price=freight,
                line_total=freight,
                tax_flag=TaxFlag.TAXABLE,
                tax_amount=freight * Decimal('0.15'),
                account_code='5030',  # Freight/Delivery
            ))
            line_index += 1

        # Add misc charges if present
        if misc > 0:
            receipt_lines.append(ReceiptLine(
                line_index=line_index,
                line_type=LineType.FEE,
                raw_text="Miscellaneous Charges",
                item_description="Misc Fees",
                quantity=Decimal('1'),
                unit_price=misc,
                line_total=misc,
                tax_flag=TaxFlag.TAXABLE,
                tax_amount=misc * Decimal('0.15'),
                account_code='5010',  # COGS - Inventory
            ))

        logger.info("grosnor_parser_completed",
                   invoice=invoice_number,
                   order=order_number,
                   lines=len(receipt_lines),
                   total=float(total))

        return ReceiptNormalized(
            entity=entity,
            source=ReceiptSource.MANUAL,  # Will be overridden by caller
            vendor_guess="Grosnor Distribution",
            purchase_date=invoice_date,
            invoice_number=invoice_number,
            currency="CAD",
            subtotal=sales_amount + freight + misc,
            tax_total=tax_total,
            total=total,
            lines=receipt_lines,
            is_bill=True,  # Grosnor has payment terms
            payment_terms=self._extract_payment_terms(text),
            ocr_method="grosnor_parser",
            ocr_confidence=95,
        )

    def _extract_invoice_number(self, text: str) -> str:
        """Extract 6-digit invoice number"""
        match = re.search(r'INVOICE NO\.\s+(\d{6})', text)
        if match:
            return match.group(1)
        return "UNKNOWN"

    def _extract_order_number(self, text: str) -> Optional[str]:
        """Extract order number"""
        match = re.search(r'ORDER NO\.\s+(\d{6})', text)
        if match:
            return match.group(1)
        return None

    def _extract_date(self, text: str) -> datetime.date:
        """
        Extract invoice date (MM/DD/YY format)
        Example: DATE 12/03/24
        """
        match = re.search(r'DATE\s+(\d{2}/\d{2}/\d{2})', text)
        if match:
            return datetime.strptime(match.group(1), '%m/%d/%y').date()
        raise ValueError("Could not extract invoice date")

    def _extract_payment_terms(self, text: str) -> str:
        """Extract payment terms"""
        match = re.search(r'TERMS\s+([\w/]+)', text)
        if match:
            terms = match.group(1)
            # Convert common abbreviations
            if 'VISA' in terms or 'MC' in terms or 'VDCARD' in terms:
                return "Credit Card"
            return terms
        return "Unknown"

    def _extract_line_items(self, text: str) -> List[dict]:
        """
        Extract line items from invoice table.

        Format:
        Item No. | Description | Configuration | Qty Ordered | Qty Shipped | Qty B/O | UOM | Unit Price | Extended Price

        Example:
        PO23PPT  POKEMON 2023 TIN... (6/1)  6  6  0  EA  22.500  135.00
        """
        items = []

        # Pattern for line items
        # Matches: SKU Description (Config) QtyOrd QtyShip QtyBO UOM UnitPrice ExtPrice
        # Note: Description may contain (SRP$X.XX)(UPC XXXXX) patterns
        pattern = r'([A-Z0-9]+)\s+(.+?)\s+\((\d+/\d+(?:/\d+)?)\)\s+(\d+)\s+(\d+)\s+(\d+)\s+(EA|BX)\s+([\d.]+)\s+([\d.]+)'

        for match in re.finditer(pattern, text, re.MULTILINE):
            try:
                sku = match.group(1)
                description_raw = match.group(2).strip()
                configuration = match.group(3)
                qty_ordered = int(match.group(4))
                qty_shipped = int(match.group(5))
                qty_backorder = int(match.group(6))
                uom = match.group(7)
                unit_price = Decimal(match.group(8))
                extended_price = Decimal(match.group(9))

                # Extract UPC from description if present
                upc = None
                upc_match = re.search(r'\(UPC\s+(\d+)\)', description_raw)
                if upc_match:
                    upc = upc_match.group(1)

                # Clean description (remove SRP and UPC codes)
                description = re.sub(r'\(SRP\$[\d.]+\)', '', description_raw)
                description = re.sub(r'\(UPC\s+\d+\)', '', description)
                description = re.sub(r'#[\d\-]+', '', description)  # Remove reference numbers
                description = description.strip()

                items.append({
                    'sku': sku,
                    'description': description,
                    'configuration': configuration,
                    'upc': upc,
                    'qty_ordered': qty_ordered,
                    'qty_shipped': qty_shipped,
                    'qty_backorder': qty_backorder,
                    'uom': uom,
                    'unit_price': unit_price,
                    'extended_price': extended_price,
                })
            except (ValueError, IndexError) as e:
                logger.warning("grosnor_line_parse_failed", error=str(e), line=match.group(0))
                continue

        logger.info("grosnor_lines_extracted", count=len(items))
        return items

    def _extract_sales_amount(self, text: str) -> Decimal:
        """Extract sales amount (before freight and tax)"""
        match = re.search(r'SALES AMOUNT\s+([\d.]+)', text)
        if match:
            return Decimal(match.group(1))
        return Decimal('0')

    def _extract_freight(self, text: str) -> Decimal:
        """Extract freight charges"""
        match = re.search(r'FREIGHT\s+([\d.]+)', text)
        if match:
            return Decimal(match.group(1))
        return Decimal('0')

    def _extract_misc(self, text: str) -> Decimal:
        """Extract miscellaneous charges"""
        match = re.search(r'MISC\s+([\d.]+)', text)
        if match:
            return Decimal(match.group(1))
        return Decimal('0')

    def _extract_tax(self, text: str) -> Decimal:
        """Extract GST/HST total"""
        match = re.search(r'GST/HST\s+([\d.]+)', text)
        if match:
            return Decimal(match.group(1))
        return Decimal('0')

    def _extract_total(self, text: str) -> Decimal:
        """Extract invoice total"""
        match = re.search(r'TOTAL\s+([\d.]+)$', text, re.MULTILINE)
        if match:
            return Decimal(match.group(1))
        raise ValueError("Could not extract invoice total")


def parse_grosnor_invoice(text: str, entity: EntityType = EntityType.SOLEPROP) -> ReceiptNormalized:
    """
    Convenience function to parse Grosnor invoice.

    Args:
        text: OCR text from Grosnor PDF invoice
        entity: Entity type (typically soleprop for Sports store)

    Returns:
        ReceiptNormalized object
    """
    parser = GrosnorParser()
    return parser.parse(text, entity)
