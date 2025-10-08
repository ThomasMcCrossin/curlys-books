"""
GFS Canada (Gordon Food Service) Invoice Parser

Invoice Format:
- PDF invoices with tabular line items
- Categories: GR (Grocery), FR (Frozen), DY (Dairy), DS (Disposables), etc.
- Tax flags: H = HST taxable items (marked in Tax column)
- Multi-page support
- Includes fuel charges in misc
- Payment terms: Net 14 (Due Friday)

Key Fields:
- Invoice number: 10-digit (e.g., 9002081541)
- Date format: MM/DD/YYYY
- Item codes: 7-digit SKU
- Pack size format: "2x3.78 L" (qty x size unit)
- Tax: HST at 15% on taxable items (marked with H)
"""

from decimal import Decimal
from datetime import datetime
from typing import List, Optional, Dict
import re
from dataclasses import dataclass

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


@dataclass
class GFSLineItem:
    """Parsed GFS line item"""
    item_code: str
    qty_ordered: int
    qty_shipped: int
    unit: str  # CS, EA, etc.
    pack_size: str  # e.g., "2x3.78 L"
    brand: str
    description: str
    category: str  # GR, FR, DY, DS
    unit_price: Decimal
    extended_price: Decimal
    tax_flag: str  # "H" for HST taxable, empty otherwise


class GFSParser(BaseReceiptParser):
    """
    Parser for GFS Canada invoices.

    Handles:
    - Multi-page invoices
    - Line item extraction with SKUs
    - Category classification (Grocery, Frozen, Dairy, Disposables)
    - HST calculation (15% on items marked with H)
    - Fuel surcharges
    """

    # Category mapping to account codes
    CATEGORY_MAPPING = {
        'GR': '5010',  # COGS - Inventory (Grocery)
        'FR': '5010',  # COGS - Inventory (Frozen)
        'DY': '5010',  # COGS - Inventory (Dairy)
        'DS': '5015',  # COGS - Disposables
        'FUEL': '5020',  # Delivery/Freight charges
    }

    def detect_format(self, text: str) -> bool:
        """
        Detect if this is a GFS Canada invoice.

        Looks for:
        - "Gordon Food Service" or "GFS" in header
        - 10-digit invoice numbers
        - Category codes (GR, FR, DY, DS)
        """
        text_upper = text.upper()

        # Check for GFS branding
        if any(pattern in text_upper for pattern in [
            'GORDON FOOD SERVICE',
            'GFS CANADA',
            'GFSCANADA.COM'
        ]):
            return True

        # Check for GFS-specific invoice format (10-digit invoice number + category codes)
        if re.search(r'Invoice\s+\d{10}', text) and re.search(r'\b(GR|FR|DY|DS)\b', text):
            return True

        return False

    def parse(self, text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
        """
        Parse GFS invoice from OCR text.

        Args:
            text: Raw OCR text from PDF
            entity: Entity type (corp or soleprop)

        Returns:
            ReceiptNormalized object
        """
        logger.info("gfs_parser_started", entity=entity.value)

        # Extract invoice metadata
        invoice_number = self._extract_invoice_number(text)
        invoice_date = self._extract_date(text)
        due_date = self._extract_due_date(text)

        # Extract line items
        line_items = self._extract_line_items(text)

        # Extract totals
        subtotal = self._extract_subtotal(text)
        fuel_charge = self._extract_fuel_charge(text)
        tax_total = self._extract_tax(text)
        total = self._extract_total(text)

        # Convert to ReceiptLine objects
        receipt_lines = []
        line_index = 0

        for item in line_items:
            # Determine tax flag
            if item.tax_flag == 'H':
                tax_flag = TaxFlag.TAXABLE
                # Calculate tax for this line (15% HST)
                line_tax = item.extended_price * Decimal('0.15')
            else:
                tax_flag = TaxFlag.EXEMPT
                line_tax = Decimal('0')

            receipt_lines.append(ReceiptLine(
                line_index=line_index,
                line_type=LineType.ITEM,
                raw_text=f"{item.item_code} {item.description}",
                vendor_sku=item.item_code,
                item_description=f"{item.description} ({item.pack_size})",
                quantity=Decimal(str(item.qty_shipped)),
                unit_price=item.unit_price,
                line_total=item.extended_price,
                tax_flag=tax_flag,
                tax_amount=line_tax,
                account_code=self.CATEGORY_MAPPING.get(item.category, '5010'),
            ))
            line_index += 1

        # Add fuel charge as separate line if present
        if fuel_charge > 0:
            receipt_lines.append(ReceiptLine(
                line_index=line_index,
                line_type=LineType.FEE,
                raw_text="Fuel Charge",
                item_description="Fuel Surcharge",
                quantity=Decimal('1'),
                unit_price=fuel_charge,
                line_total=fuel_charge,
                tax_flag=TaxFlag.TAXABLE,
                tax_amount=fuel_charge * Decimal('0.15'),
                account_code=self.CATEGORY_MAPPING['FUEL'],
            ))

        logger.info("gfs_parser_completed",
                   invoice=invoice_number,
                   lines=len(receipt_lines),
                   total=float(total))

        return ReceiptNormalized(
            entity=entity,
            source=ReceiptSource.MANUAL,  # Will be overridden by caller
            vendor_guess="Gordon Food Service",
            purchase_date=invoice_date,
            invoice_number=invoice_number,
            due_date=due_date,
            currency="CAD",
            subtotal=subtotal + fuel_charge,
            tax_total=tax_total,
            total=total,
            lines=receipt_lines,
            is_bill=True,  # GFS is Net 14 terms
            payment_terms="Net 14",
            ocr_method="gfs_parser",
            ocr_confidence=95,
        )

    def _extract_invoice_number(self, text: str) -> str:
        """Extract 10-digit invoice number"""
        match = re.search(r'Invoice\s+(\d{10})', text)
        if match:
            return match.group(1)
        return "UNKNOWN"

    def _extract_date(self, text: str) -> datetime.date:
        """Extract invoice date (MM/DD/YYYY format)"""
        # Try standard format first
        match = re.search(r'Invoice Date\s+(\d{2}/\d{2}/\d{4})', text)
        if match:
            return datetime.strptime(match.group(1), '%m/%d/%Y').date()

        # Try format where date is on next line after Invoice Date
        match = re.search(r'Invoice Date.*?[\n\r]+.*?(\d{2}/\d{2}/\d{4})', text, re.DOTALL)
        if match:
            return datetime.strptime(match.group(1), '%m/%d/%Y').date()

        raise ValueError("Could not extract invoice date")

    def _extract_due_date(self, text: str) -> Optional[datetime.date]:
        """Extract due date"""
        match = re.search(r'Due Date\s+(\d{2}/\d{2}/\d{4})', text)
        if match:
            return datetime.strptime(match.group(1), '%m/%d/%Y').date()
        return None

    def _extract_line_items(self, text: str) -> List[GFSLineItem]:
        """
        Extract line items from invoice table.

        Format (PDF extraction may vary):
        ItemCode Qty Description Category UnitPrice ExtPrice [Tax] Unit QtyShip PackSize Brand
        1229832 5 APPETIZER ONION RING BTD FR 22.52 112.60 CS 5 1X3 KG Kitche
        """
        items = []

        # Pattern for line items - handles PDF extraction format
        # ItemCode Qty Description Cat UnitPrice ExtPrice [H] Unit QtyShip PackSize Brand
        pattern = r'(\d{7})\s+(\d+)\s+(.+?)\s+(GR|FR|DY|DS|CP)\s+([\d.]+)\s+([\d.]+)\s+([H])?\s*(CS|EA)\s+(\d+)\s+([\dXx.]+\s*[A-Z]+)\s+(\w+)'

        for match in re.finditer(pattern, text, re.MULTILINE):
            try:
                items.append(GFSLineItem(
                    item_code=match.group(1),
                    qty_ordered=int(match.group(2)),
                    qty_shipped=int(match.group(9)),
                    unit=match.group(8),
                    pack_size=match.group(10),
                    brand=match.group(11),
                    description=match.group(3).strip(),
                    category=match.group(4),
                    unit_price=Decimal(match.group(5)),
                    tax_flag=match.group(7) or '',
                    extended_price=Decimal(match.group(6)),
                ))
            except (ValueError, IndexError) as e:
                logger.warning("gfs_line_parse_failed", error=str(e), line=match.group(0))
                continue

        logger.info("gfs_lines_extracted", count=len(items))
        return items

    def _extract_subtotal(self, text: str) -> Decimal:
        """Extract product subtotal (before fuel and tax)"""
        match = re.search(r'Product Total\s+\$?([\d,]+\.\d{2})', text)
        if match:
            return Decimal(match.group(1).replace(',', ''))
        return Decimal('0')

    def _extract_fuel_charge(self, text: str) -> Decimal:
        """Extract fuel surcharge from Misc line"""
        match = re.search(r'Misc\s+\$?([\d,]+\.\d{2})', text)
        if match:
            amount = Decimal(match.group(1).replace(',', ''))
            if amount > 0:
                logger.info("gfs_fuel_charge_found", amount=float(amount))
            return amount
        return Decimal('0')

    def _extract_tax(self, text: str) -> Decimal:
        """Extract HST total"""
        match = re.search(r'GST/HST\s+\$?([\d,]+\.\d{2})', text)
        if match:
            return Decimal(match.group(1).replace(',', ''))
        return Decimal('0')

    def _extract_total(self, text: str) -> Decimal:
        """Extract invoice total"""
        match = re.search(r'Invoice Total\s+\$?([\d,]+\.\d{2})', text)
        if match:
            return Decimal(match.group(1).replace(',', ''))
        raise ValueError("Could not extract invoice total")


def parse_gfs_invoice(text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
    """
    Convenience function to parse GFS invoice.

    Args:
        text: OCR text from GFS PDF invoice
        entity: Entity type (corp or soleprop)

    Returns:
        ReceiptNormalized object
    """
    parser = GFSParser()
    return parser.parse(text, entity)
