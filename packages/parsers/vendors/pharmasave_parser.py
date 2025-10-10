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

        Format:
        QTY  ITEM #    DESCRIPTION           AMOUNT
        1    10035     SCOTSBURN COFFEE      5.05EN
        1    267219    SCOTSBURN 2% MILK 2L  4.19EN
        1    759368    SPRITE                6.08TN
        1    243199    DEPOSIT CANS/BOTTLES  0.60EN

        Tax flags: EN = HST exempt/zero-rated, TN = HST taxable, TY = ?

        Deposits are tracked as separate FEE line items since they're expenses
        but not COGS (cost of goods sold).
        """
        lines = []

        # Pattern to match line items
        # Format: QTY ITEM# DESCRIPTION AMOUNT(with tax flag)
        # Example: "1    10035     SCOTSBURN COFFEE      5.05EN"
        line_pattern = r'^\s*(\d+)\s+(\d{5,})\s+(.+?)\s+([0-9.]+)(EN|TN|TY)\s*$'

        for match in re.finditer(line_pattern, text, re.MULTILINE):
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

        logger.info("pharmasave_lines_extracted", count=len(lines))
        return lines
