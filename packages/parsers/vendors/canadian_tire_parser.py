"""
Canadian Tire Parser

Handles Canadian Tire POS receipts (including refunds) with CT Money messaging.

Observed features (sample March 7, 2023 image receipt):
- "Visit canadiantire.ca" footer and CT Money section
- "ORIG PURCHASE DATE: MM/DD/YYYY"
- Line items like: "-1X063-060B-6 ADAPTER, FAUCET-  $ -7.49"
  or multi-qty with unit price line: "-2X063-0806-4 COUPLING, GARDEN $ -26.38" then
  next line "@ $ -13.190 ea" (unit line can be ignored)
- Footer totals block (refund example):
  SUBTOTAL $ -46.03
  15% HST $ -6.90
  T O T A L $ -52.93
  eCTM REFUND $ 52.93

Parsing notes:
- Canadian Tire refunds show negative amounts. Schema requires non-negative totals,
  so this parser stores absolute values for subtotal/tax/total and line totals.
  A parsing note is added when a refund is detected.
- All items assumed TAXABLE (HST applies) unless future patterns indicate otherwise.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

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


class CanadianTireParser(BaseReceiptParser):
    """Parser for Canadian Tire retail receipts/refunds."""

    VENDOR_NAME = "Canadian Tire"

    def detect_format(self, text: str) -> bool:
        """Heuristics to recognize Canadian Tire receipts.

        Looks for brand terms and common footer/header markers.
        """
        text_upper = text.upper()
        indicators = [
            r"CANADIAN\s+TIRE",              # explicit brand
            r"CANADIANTIRE\.CA",             # website footer
            r"MY\s+CT\s+'?MONEY'?,?\s+ACCOUNT",  # CT Money section
            r"E?CTM\s+REFUND",               # CT Money refund line
            r"HST\s+REG\.?\s*#\s*\d+",     # tax registration
        ]
        for pat in indicators:
            if re.search(pat, text_upper):
                return True
        return False

    def parse(self, text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
        logger.info("canadiantire_parse_start")

        # Receipt/transaction number
        invoice = self._extract_invoice_number(text)

        # Date (ORIG PURCHASE DATE: MM/DD/YYYY)
        purchase_date = self._extract_date(text)

        # Totals (handle negatives on refunds)
        raw_subtotal, raw_tax, raw_total = self._extract_totals(text)
        is_refund = any(v is not None and v < 0 for v in (raw_subtotal, raw_tax, raw_total))

        subtotal = abs(raw_subtotal or Decimal("0"))
        tax_total = abs(raw_tax or Decimal("0"))
        total = abs(raw_total or (subtotal + tax_total))

        # Line items
        lines = self._extract_line_items(text)

        # Backfill missing/faded items so lines sum to subtotal
        lines = self.handle_missing_line_items(
            lines=lines, subtotal=subtotal, vendor_name=self.VENDOR_NAME
        )

        parsing_errors: Optional[List[str]] = None
        if is_refund:
            parsing_errors = [
                "Vendor printed this as a REFUND/return; amounts stored as absolute values to satisfy schema."
            ]

        receipt = ReceiptNormalized(
            entity=entity,
            source=ReceiptSource.MANUAL,
            vendor_guess=self.VENDOR_NAME,
            purchase_date=purchase_date or datetime.now().date(),
            invoice_number=invoice,
            currency="CAD",
            subtotal=subtotal,
            tax_total=tax_total,
            total=total,
            lines=lines,
            is_bill=False,
            ocr_method="tesseract/gpt-mixed",
            parsing_errors=parsing_errors,
        )

        logger.info(
            "canadiantire_parse_done",
            invoice=invoice,
            date=str(receipt.purchase_date),
            subtotal=float(subtotal),
            tax=float(tax_total),
            total=float(total),
            lines=len(lines),
            refund=is_refund,
        )
        return receipt

    # ---------------------- helpers ----------------------

    def _extract_invoice_number(self, text: str) -> Optional[str]:
        # Examples: "ORIG TRN ID: 000032303030..." or various barcode IDs
        m = re.search(r"ORIG\s+TRN\s+ID[:\s]*([0-9A-Z]{8,})", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # Fallback: last long numeric near barcode
        m = re.search(r"\n\s*([0-9]{12,})\s*\n", text)
        return m.group(1).strip() if m else None

    def _extract_date(self, text: str):
        # Primary: ORIG PURCHASE DATE: 03/07/2023
        dm = re.search(r"ORIG\s+PURCHASE\s+DATE[:\s]+(\d{1,2})/(\d{1,2})/(\d{2,4})", text, re.IGNORECASE)
        if dm:
            mm, dd, yyyy = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
            yyyy = 2000 + yyyy if yyyy < 100 else yyyy
            try:
                return datetime(yyyy, mm, dd).date()
            except ValueError:
                logger.warning("canadiantire_date_parse_failed", raw=dm.group(0))
        # Secondary: top header date like 03/10/2023 11:16
        dm2 = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
        if dm2:
            mm, dd, yyyy = int(dm2.group(1)), int(dm2.group(2)), int(dm2.group(3))
            yyyy = 2000 + yyyy if yyyy < 100 else yyyy
            try:
                return datetime(yyyy, mm, dd).date()
            except ValueError:
                pass
        return None

    def _extract_totals(self, text: str):
        """Return tuple (subtotal, tax, total) as Decimals (possibly negative)."""
        def amt(pat: str) -> Optional[Decimal]:
            return self.extract_amount(text, pat)

        # SUBTOTAL (look for the word SUBTOTAL followed by amount)
        subtotal = amt(r"SUBTOTAL\s+\$\s*([-0-9.,]+)")

        # HST/GST/QST/PST line (avoid HST REG #, look for percentage prefix like "15% HST")
        tax = amt(r"(?:\d{1,2}\s*%\s*)?(?:HST|GST|PST|QST)(?!\s*REG)\s+\$\s*([-0-9.,]+)")

        # TOTAL (Canadian Tire often prints with spaces: T O T A L)
        # Use word boundary to avoid matching "eCTM" or other text
        total = amt(r"(?:^|\n)\s*T\s*O\s*T\s*A\s*L\s+\$\s*([-0-9.,]+)")

        return subtotal, tax, total

    def _extract_line_items(self, text: str) -> List[ReceiptLine]:
        lines: List[ReceiptLine] = []

        # Pattern for item lines like: "-2X063-0806-4 COUPLING, GARDEN  $ -26.38"
        # Notes:
        #  - Optional leading dash (returns)
        #  - Qty followed by 'X' glued to SKU
        #  - Description until a $ amount
        item_pat = re.compile(
            r"^\s*-?\s*(?P<qty>\d+)X(?P<sku>[A-Z0-9\-]+)\s+(?P<desc>.+?)\s+\$\s*(?P<amt>[-0-9.,]+)\s*$",
            re.IGNORECASE | re.MULTILINE,
        )

        # Ignore per-unit lines like "@ $ -13.190 ea"
        ignore_unit_pat = re.compile(r"^\s*@\s*\$\s*[-0-9.,]+\s*ea\.?\s*$", re.IGNORECASE | re.MULTILINE)
        text_wo_unit = ignore_unit_pat.sub("", text)

        for m in item_pat.finditer(text_wo_unit):
            qty = Decimal(m.group("qty"))
            sku = m.group("sku").strip()
            desc = self.clean_description(m.group("desc"))
            amount = self.normalize_price(m.group("amt"))

            # Schema uses positive amounts; store absolute value
            line_total = abs(amount)

            # Canadian Tire retail items are generally taxable (HST)
            tax_flag = TaxFlag.TAXABLE

            # Build line
            lines.append(
                ReceiptLine(
                    line_index=len(lines),
                    line_type=LineType.ITEM,
                    raw_text=m.group(0).strip(),
                    vendor_sku=sku,
                    item_description=desc,
                    quantity=qty,
                    unit_price=line_total,  # Receipts show line totals; keep same for simplicity
                    line_total=line_total,
                    tax_flag=tax_flag,
                )
            )

        logger.info("canadiantire_lines_extracted", count=len(lines))
        return lines
