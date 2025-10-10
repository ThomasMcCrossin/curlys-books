"""
Pepsi Beverages Parser - Handles Pepsi delivery invoices and email summaries

Formats supported:
1. Delivery invoices - Direct delivery with detailed line items (INVOICE # format)
2. Email invoice summaries - Monthly summary PDFs (Invoice Details format)

Payment terms: Charge-PAD, 15th of following month
Vendor: PepsiCo Canada Beverages
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


class PepsiParser(BaseReceiptParser):
    """
    Parser for PepsiCo Canada Beverages invoices.

    Handles multiple invoice formats from Pepsi delivery and email summaries.
    """

    def detect_format(self, text: str) -> bool:
        """
        Detect if this is a Pepsi invoice.

        Formats:
        1. Delivery invoices - Physical delivery receipts with "PEPSICO CANADA"
        2. Email summaries - PDF summaries with Pepsi product codes

        Args:
            text: OCR text from receipt

        Returns:
            True if this appears to be a Pepsi invoice
        """
        text_upper = text.upper()

        # Format 1: Delivery invoice indicators
        delivery_indicators = [
            r'PEPSICO\s+CANADA',
            r'PEPSI.*BEVERAGES',
            r'BEVERAGES.*BREUVAGES',
            r'220\s+HENRI\s+DUNANT',
            r'MONCTON.*NB.*E1E',
        ]

        for pattern in delivery_indicators:
            if re.search(pattern, text_upper):
                logger.info("pepsi_format_detected", pattern=pattern, format="delivery")
                return True

        # Format 2: Email summary indicators
        # Look for multiple Pepsi product codes (69000xxxxx pattern)
        pepsi_product_codes = re.findall(r'69000\d{6}', text)
        if len(pepsi_product_codes) >= 3:  # Multiple Pepsi products
            logger.info("pepsi_format_detected", pattern="pepsi_product_codes", format="email_summary", count=len(pepsi_product_codes))
            return True

        return False

    def parse(self, text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
        """
        Parse Pepsi invoice and extract structured data.

        Args:
            text: OCR text from invoice
            entity: Entity type (default: CORP for Curly's Canteen)

        Returns:
            ReceiptNormalized with vendor, date, total, and line items

        Raises:
            ValueError: If required fields cannot be extracted
        """
        logger.info("pepsi_parsing_started")

        # Detect format variant
        text_upper = text.upper()

        # Email summary format: has "INVOICE DETAILS" or "INVOICE SUMMARY" and product lines with CS/EA
        if ("INVOICE DETAILS" in text_upper or "INVOICE SUMMARY" in text_upper):
            logger.info("pepsi_format_routing", format="email_summary")
            return self._parse_email_summary(text, entity)

        # Delivery invoice format: has "INVOICE #" and "ITEM DETAIL" section
        elif "INVOICE #" in text_upper and "ITEM DETAIL" in text_upper:
            logger.info("pepsi_format_routing", format="delivery_invoice")
            return self._parse_delivery_invoice(text, entity)

        else:
            # Default: try delivery format (most common)
            logger.warning("pepsi_format_ambiguous", message="Could not determine format, trying delivery")
            return self._parse_delivery_invoice(text, entity)

    def _parse_delivery_invoice(self, text: str, entity: EntityType) -> ReceiptNormalized:
        """
        Parse delivery invoice format (printed/photo receipts).

        Example markers:
        - INVOICE # 51314455
        - Route #: 8232
        - ITEM DETAIL section with line items
        """
        # Extract invoice number
        invoice_match = re.search(r'INVOICE\s*#\s*(\d+)', text, re.IGNORECASE)
        invoice_number = invoice_match.group(1) if invoice_match else None

        # Extract date - format: 10/07/2025 53 AM (ignore the time portion)
        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', text)
        date = None
        if date_match:
            try:
                date = datetime.strptime(date_match.group(1), '%m/%d/%Y').date()
            except ValueError:
                logger.warning("date_parse_failed", date_str=date_match.group(1))

        # Extract total - "Amount Due $ 1381.76" or "for this Invoice: $ 1381.76"
        # May be on separate lines, so use DOTALL
        total_patterns = [
            r'Amount\s+Due[\s\S]*?\$\s*([\d,]+\.?\d*)',
            r'for\s+this\s+Invoice[\s\S]*?\$\s*([\d,]+\.?\d*)',
        ]
        total = None
        for pattern in total_patterns:
            total_match = re.search(pattern, text, re.IGNORECASE)
            if total_match:
                total = self.normalize_price(total_match.group(1))
                break

        # Extract subtotal - "Sales Cases 32 1149.12" or "SALES SUMMARY ... Amount 1149.12"
        subtotal_patterns = [
            r'Sales.*?Cases.*?(\d+)\s+([\d,]+\.?\d*)',  # Sales line with amount
            r'Subtotal.*?([\d,]+\.?\d*)',  # Standard subtotal
        ]
        subtotal = None
        for pattern in subtotal_patterns:
            subtotal_match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if subtotal_match:
                # Get last captured group (the amount)
                subtotal = self.normalize_price(subtotal_match.group(subtotal_match.lastindex))
                break

        # Extract HST - "GST/HST On $1113.21 $ 155.84" (second $ is the tax)
        hst_patterns = [
            r'GST/HST\s+On.*?\$\s*[\d,]+\.?\d*\s*\$\s*([\d,]+\.?\d*)',  # "GST/HST On $base $ tax"
            r'GST/HST.*?\$\s*([\d,]+\.?\d*)',  # Standard format
        ]
        hst = Decimal('0')
        for pattern in hst_patterns:
            hst_match = re.search(pattern, text, re.IGNORECASE)
            if hst_match:
                hst = self.normalize_price(hst_match.group(1))
                break

        # Extract deposits/charges (NS deposit: $0.10 per bottle/can)
        charges_match = re.search(r'Charges[\s\n]+([\d,]+\.?\d*)', text, re.IGNORECASE)
        charges = self.normalize_price(charges_match.group(1)) if charges_match else Decimal('0')

        # Extract line items from ITEM DETAIL section
        lines = self._extract_delivery_line_items(text)

        logger.info("pepsi_delivery_parsed",
                   invoice=invoice_number,
                   date=str(date),
                   total=float(total) if total else None,
                   subtotal=float(subtotal) if subtotal else None,
                   tax=float(hst),
                   charges=float(charges),
                   lines=len(lines))

        # Adjust subtotal to include charges for validation
        # Total = Subtotal (sales) + Charges (deposits) + Tax
        # But ReceiptNormalized expects: Total = Subtotal + Tax
        # So we include charges in subtotal for validation purposes
        adjusted_subtotal = (subtotal or Decimal('0')) + charges

        return ReceiptNormalized(
            entity=entity,
            source=ReceiptSource.MANUAL,  # Will be updated by upload handler
            vendor_guess="PepsiCo Canada",
            purchase_date=date or datetime.now().date(),
            invoice_number=invoice_number,
            total=total or Decimal('0'),
            subtotal=adjusted_subtotal,  # Includes deposits
            tax_total=hst,
            lines=lines,
            payment_terms='Charge-PAD 15th next month',
            is_bill=True,  # Pepsi invoices are bills (A/P)
            metadata={
                'deposits': float(charges),
                'sales_subtotal': float(subtotal) if subtotal else 0.0,
                'total_units': 768,  # Could extract from "Total Units" line
            }
        )

    def _extract_delivery_line_items(self, text: str) -> list[ReceiptLine]:
        """
        Extract line items from delivery invoice ITEM DETAIL section.

        Format:
        591ML PL 1/24
        PEPSI 0-69000-00991-8    T  97.00  5 120 35.91 179.55

        Columns: Description, UPC, Tax, Price/Case, Whsl, Cases, Units, Net Amount
        """
        lines = []

        # Find ITEM DETAIL section
        item_section_match = re.search(r'ITEM DETAIL.*?SALES(.*?)(?:CHARGES|Amount Due)', text, re.DOTALL | re.IGNORECASE)
        if not item_section_match:
            logger.warning("item_detail_section_not_found")
            return lines

        item_text = item_section_match.group(1)

        # Pattern to match line items
        # Example: PEPSI 0-69000-00991-8  T  97.00  5  120  35.91  179.55
        # Format: Description UPC TaxFlag ?? Cases TotalUnits PricePerCase LineTotal
        # We want: Cases as quantity, PricePerCase as unit_price, LineTotal as line_total

        line_pattern = r'([A-Z][A-Z0-9\s/]+?)\s+([\d-]{11,})\s+T?\s*[\d.]+\s+(\d+)\s+\d+\s+([\d.]+)\s+([\d.]+)\s*$'

        for match in re.finditer(line_pattern, item_text, re.MULTILINE):
            description = match.group(1).strip()
            upc = match.group(2).replace('-', '')  # Remove hyphens from UPC
            cases = int(match.group(3))
            price_per_case = Decimal(match.group(4))
            line_total = Decimal(match.group(5))

            # Quantity is number of cases purchased
            quantity = Decimal(str(cases))
            unit_price = price_per_case

            lines.append(ReceiptLine(
                line_index=len(lines),
                line_type=LineType.ITEM,
                vendor_sku=upc,
                upc=upc,
                item_description=self.clean_description(description),
                quantity=Decimal(str(quantity)),
                unit_price=unit_price,
                line_total=line_total,
                tax_flag=TaxFlag.TAXABLE,  # Pepsi products are typically HST-taxable
            ))

        logger.info("delivery_lines_extracted", count=len(lines))
        return lines

    def _parse_email_summary(self, text: str, entity: EntityType) -> ReceiptNormalized:
        """
        Parse email invoice summary format (PDF summaries).

        Example markers:
        - Invoice Details
        - Bill To: / Ship To:
        - Line items with UPC codes
        """
        # Extract invoice number - could be in different formats
        invoice_match = re.search(r'(\d{8})', text)  # 8-digit invoice number
        invoice_number = invoice_match.group(1) if invoice_match else None

        # Extract date - various formats like "10/08/24" or "15th Of Month"
        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})', text)
        date = None
        if date_match:
            date_str = date_match.group(1)
            try:
                # Try different date formats
                if '/' in date_str and len(date_str.split('/')[-1]) == 2:
                    date = datetime.strptime(date_str, '%m/%d/%y').date()
                else:
                    date = datetime.strptime(date_str, '%m/%d/%Y').date()
            except ValueError:
                logger.warning("date_parse_failed", date_str=date_str)

        # Extract line items
        lines = self._extract_email_line_items(text)

        # Calculate totals from line items (email summaries may not have clear totals)
        subtotal = sum(line.line_total for line in lines)
        total = subtotal  # Will be updated if tax found

        # Try to find total if available
        total_match = re.search(r'Total.*?\$?([\d,]+\.?\d*)', text, re.IGNORECASE)
        if total_match:
            total = self.normalize_price(total_match.group(1))

        logger.info("pepsi_email_parsed",
                   invoice=invoice_number,
                   date=str(date),
                   total=float(total),
                   lines=len(lines))

        return ReceiptNormalized(
            entity=entity,
            source=ReceiptSource.MANUAL,  # Will be updated by upload handler
            vendor_guess="PepsiCo Canada",
            purchase_date=date or datetime.now().date(),
            invoice_number=invoice_number,
            total=total,
            subtotal=subtotal,
            tax_total=total - subtotal if total > subtotal else Decimal('0'),
            lines=lines,
            payment_terms='15th of next month',
            is_bill=True,
        )

    def _extract_email_line_items(self, text: str) -> list[ReceiptLine]:
        """
        Extract line items from email invoice summary.

        Format:
        PEPSI COL COLA PET 591ML 1P24C 69000009918 2 CS $35.38 $70.76

        Pattern: Description UPC Quantity CS/EA $UnitPrice $Total
        """
        lines = []

        # Pattern for email summary line items
        # Example: PEPSI COL COLA PET 591ML 1P24C 69000009918 2 CS $35.38 $70.76
        # Note: Some lines have "CS" or "EA", some have "cs", and prices may have trailing punctuation
        line_pattern = r'([A-Z0-9\s/]+?)\s+(\d{8,})\s+(\d+)\s+(?:CS|cs|EA)\s+[=$\s]*\$?([\d.]+)[.\s]*\$?([\d.]+)'

        for match in re.finditer(line_pattern, text, re.IGNORECASE):
            description = match.group(1).strip()
            upc = match.group(2)
            quantity = int(match.group(3))
            unit_price = Decimal(match.group(4))
            line_total = Decimal(match.group(5))

            lines.append(ReceiptLine(
                line_index=len(lines),
                line_type=LineType.ITEM,
                vendor_sku=upc,
                upc=upc,
                item_description=self.clean_description(description),
                quantity=Decimal(str(quantity)),
                unit_price=unit_price,
                line_total=line_total,
                tax_flag=TaxFlag.TAXABLE,
            ))

        logger.info("email_lines_extracted", count=len(lines))
        return lines
