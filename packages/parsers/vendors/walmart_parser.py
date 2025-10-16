"""
Walmart Canada Parser

Handles common Walmart / Walmart Supercentre receipts in Canada (HST/GST/PST).

Key features:
- Robust vendor detection ("WALMART", "WALMART SUPERCENTRE", slogans, TC# markers)
- Flexible date extraction for multiple print formats
- Extracts SUBTOTAL, tax components (HST/GST/PST/QST), and TOTAL
- Line-item extraction with deposit/eco fee detection
- Tax flags: TAXABLE (Y) vs ZERO_RATED (Z) inference from codes/keywords
- Automatic placeholder for faded/missing lines to make subtotal validate
- Validates against ReceiptNormalized (subtotal + tax_total == total ±$0.02)

Notes:
- Walmart line formats vary. This parser captures the most common patterns (single-line items ending with amount, optional tax code letter like "T").
- Weighted produce often prints helper lines (e.g., "0.72kg @ 1.67/kg"); the parser focuses on the priced item line.
"""

from __future__ import annotations

import re
from datetime import datetime, date
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


class WalmartCanadaParser(BaseReceiptParser):
    """Parser for Walmart / Walmart Supercentre receipts in Canada."""

    VENDOR_PATTERNS = [
        r"\bWALMART\b",
        r"\bWALMART\s+SUPERCENTRE\b",
        r"SAVE\s+MONEY\.?\s+LIVE\s+BETTER\.?",
        r"\bTC#\b|\bTR#\b|\bTRANS#\b",
    ]

    # Lines that are definitely not items
    NON_ITEM_PREFIX = (
        r"SUB\s*TOTAL|TOTAL\b|CHANGE\b|CASH\b|DEBIT\b|CREDIT\b|VISA\b|MASTERCARD\b|"
        r"ROUND(ING)?\b|AMOUNT\s+TENDERED|BALANCE\s+DUE|APPROVAL|AID:|RID:|A000|TC|ERMINAL|"
        r"HST\b|GST\b|PST\b|QST\b|TAX\b|COUPON|SAV(ING|E)S|RETURN|REFUND|SUB-?TOTAL|"
        r"NS\s+DEPOSIT|DEPOSIT|MULTI\s+DISCOUNT"  # Exclude deposits and metadata lines
    )

    # Walmart format: DESCRIPTION UPC $AMOUNT TAXCODE
    # Example: CANADA DRY A 062100008930 $6.98 J
    # Example: BUBLY LIME 069000149180 $5.97 J
    ITEM_LINE_RE = re.compile(
        rf"^(?!\s*(?:{NON_ITEM_PREFIX}))\s*"  # not a footer/control line
        r"(?P<desc>[A-Z][A-Z0-9\s&%/.,()*'#]+?)\s+"  # Description (caps, starts with letter)
        r"(?P<upc>\d{12})\s+"  # 12-digit UPC
        r"\$?(?P<amount>\d+\.\d{2})\s*"  # Price with optional $
        r"(?P<taxcode>[A-Z0-9])?\s*$",  # Tax code (H, J, D, etc)
        re.MULTILINE,
    )

    # Promotional adjustment format: "PEPSI 2 FOR $14 006L $7.84-A"
    # This captures multi-buy promo discounts that have promo text in middle
    PROMO_LINE_RE = re.compile(
        r"^(?P<desc>[A-Z][A-Z0-9\s&]+?)\s+"  # Description
        r"(?P<promo>\d+\s+FOR\s+\$\d+\.?\d{0,2})\s+"  # Promo text like "2 FOR $14"
        r"(?P<size>[\dL]+)\s+"  # Size like "006L"
        r"\$?(?P<amount>\d+\.\d{2})-(?P<taxcode>[A-Z])\s*$",  # Amount with negative sign immediately before tax code
        re.MULTILINE,
    )

    # Some receipts show item first, then a next line with an override price; we still
    # pick up the priced line via ITEM_LINE_RE. Helper/metadata-only lines are ignored.

    def detect_format(self, text: str) -> bool:
        text_up = text.upper()
        for pat in self.VENDOR_PATTERNS:
            if re.search(pat, text_up, re.MULTILINE):
                logger.info("walmart_format_detected", pattern=pat)
                return True
        return False

    def parse(self, text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
        logger.info("walmart_parsing_started")

        date_val = self._extract_date(text)
        receipt_no = self._extract_receipt_number(text)

        subtotal = self._extract_subtotal(text) or Decimal("0")
        tax_total = self._extract_tax_total(text)
        total = self._extract_total(text) or (subtotal + tax_total)

        lines = self._extract_lines(text)
        lines, validation_warning = self.handle_missing_line_items(
            lines=lines, subtotal=subtotal, vendor_name="Walmart"
        )

        # Build validation_warnings list if there are any warnings
        validation_warnings = [validation_warning] if validation_warning else None

        logger.info(
            "walmart_parsed",
            date=str(date_val),
            receipt_no=receipt_no,
            subtotal=float(subtotal),
            tax=float(tax_total),
            total=float(total),
            lines=len(lines),
        )

        return ReceiptNormalized(
            entity=entity,
            source=ReceiptSource.MANUAL,  # updated by uploader
            vendor_guess=self._guess_vendor_name(text),
            purchase_date=date_val or datetime.now().date(),
            invoice_number=receipt_no,
            currency="CAD",
            subtotal=subtotal,
            tax_total=tax_total,
            total=total,
            lines=lines,
            is_bill=False,
            validation_warnings=validation_warnings,
        )

    # ----------------------- helpers -----------------------

    def _guess_vendor_name(self, text: str) -> str:
        if re.search(r"WALMART\s+SUPERCENTRE", text, re.IGNORECASE):
            return "Walmart Supercentre"
        return "Walmart"

    def _extract_receipt_number(self, text: str) -> Optional[str]:
        m = re.search(r"\bTC#\s*([0-9\s-]+)", text, re.IGNORECASE)
        if not m:
            m = re.search(r"\bTR#\s*([0-9\s-]+)", text, re.IGNORECASE)
        if not m:
            m = re.search(r"\bTRANS#?\s*([0-9\s-]+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def _extract_date(self, text: str) -> Optional[date]:
        # Prefer YYYY-MM-DD or YYYY/MM/DD
        for pat, fmt in [
            (r"(20\d{2})[\-/](\d{1,2})[\-/](\d{1,2})", "%Y-%m-%d"),
            (r"(\d{1,2})[\-/](\d{1,2})[\-/](20\d{2})", "%m-%d-%Y"),
            (r"(\d{1,2})[\-/](\d{1,2})[\-/](\d{2})", "%m-%d-%y"),
        ]:
            m = re.search(pat, text)
            if m:
                g = m.groups()
                try:
                    if fmt == "%Y-%m-%d":
                        y, mo, d = int(g[0]), int(g[1]), int(g[2])
                        return datetime(y, mo, d).date()
                    elif fmt == "%m-%d-%Y":
                        mo, d, y = int(g[0]), int(g[1]), int(g[2])
                        # flip if day > 12 and likely D/M/Y
                        if mo > 12 and d <= 12:
                            mo, d = d, mo
                        return datetime(y, mo, d).date()
                    else:  # %m-%d-%y -> assume 20xx
                        mo, d, yy = int(g[0]), int(g[1]), int(g[2])
                        y = 2000 + yy
                        if mo > 12 and d <= 12:
                            mo, d = d, mo
                        return datetime(y, mo, d).date()
                except ValueError:
                    continue
        return None

    def _extract_total(self, text: str) -> Optional[Decimal]:
        # Avoid matching SUBTOTAL or TOTAL SAVINGS
        m = re.search(r"(?i)(?<!SUB\s)\bTOTAL\b(?!\s*SAV)\s*[: ]\$?([0-9][0-9,]*\.\d{2})", text)
        return self.normalize_price(m.group(1)) if m else None

    def _extract_subtotal(self, text: str) -> Optional[Decimal]:
        m = re.search(r"(?i)SUB\s*-?\s*TOTAL\s*[: ]\$?([0-9][0-9,]*\.\d{2})", text)
        if not m:
            # Some receipts print just "SUBTOTAL"
            m = re.search(r"(?i)SUBTOTAL\s*[: ]\$?([0-9][0-9,]*\.\d{2})", text)
        return self.normalize_price(m.group(1)) if m else None

    def _extract_tax_total(self, text: str) -> Decimal:
        tax_total = Decimal("0")
        # HST (Atlantic provinces), GST/PST/QST (others)
        # Format: "HST 14.0000 % $13.00" - we want the dollar amount, not the percentage
        for label in ["HST", "GST", "PST", "QST"]:
            m = re.search(rf"(?i)\b{label}\b[^$\n]*\$([0-9][0-9,]*\.\d{{2}})", text)
            if m:
                try:
                    tax_total += self.normalize_price(m.group(1))
                except Exception:
                    pass
        # Fallback: compute from total - subtotal when explicit tax lines are missing
        if tax_total == 0:
            maybe_total = self._extract_total(text)
            maybe_sub = self._extract_subtotal(text)
            if maybe_total is not None and maybe_sub is not None:
                diff = maybe_total - maybe_sub
                if abs(diff) <= Decimal("9999"):  # sanity
                    tax_total = diff
        return tax_total

    def _extract_lines(self, text: str) -> List[ReceiptLine]:
        lines: List[ReceiptLine] = []
        idx = 0

        # Extract regular items (DESC UPC $AMOUNT CODE)
        for m in self.ITEM_LINE_RE.finditer(text):
            desc_raw = m.group("desc").strip()
            upc = m.group("upc")
            amount = self.normalize_price(m.group("amount"))
            taxcode = (m.group("taxcode") or "").upper().strip()

            # Skip deposits that snuck through
            if "DEPOSIT" in desc_raw.upper():
                continue

            # Deposit / eco fee detection
            is_fee = self._is_deposit_or_fee(desc_raw)
            line_type = LineType.FEE if is_fee else LineType.ITEM

            tax_flag = self._infer_tax_flag(taxcode, desc_raw)

            lines.append(
                ReceiptLine(
                    line_index=idx,
                    line_type=line_type,
                    raw_text=m.group(0).strip(),
                    vendor_sku=upc,  # Store UPC as vendor SKU
                    upc=upc,
                    item_description=self.clean_description(desc_raw),
                    quantity=Decimal("1"),
                    unit_price=amount,
                    line_total=amount,
                    tax_flag=tax_flag,
                )
            )
            idx += 1

        # Extract promotional discount lines (DESC PROMO SIZE $AMOUNT-CODE)
        for m in self.PROMO_LINE_RE.finditer(text):
            desc_raw = m.group("desc").strip()
            promo = m.group("promo").strip()
            size = m.group("size").strip()
            amount = self.normalize_price(m.group("amount"))
            taxcode = m.group("taxcode").upper().strip()

            # Promotional lines are negative adjustments (discounts)
            amount = -amount

            # Build description with promo details
            full_desc = f"{desc_raw} ({promo} {size})"

            tax_flag = self._infer_tax_flag(taxcode, desc_raw)

            lines.append(
                ReceiptLine(
                    line_index=idx,
                    line_type=LineType.ITEM,  # Promo discount is item adjustment
                    raw_text=m.group(0).strip(),
                    vendor_sku=None,  # No UPC for promo lines
                    upc=None,
                    item_description=self.clean_description(full_desc),
                    quantity=Decimal("1"),
                    unit_price=amount,
                    line_total=amount,
                    tax_flag=tax_flag,
                )
            )
            idx += 1

        logger.info("walmart_lines_extracted", count=len(lines))
        return lines

    # ------------------ heuristics ------------------

    def _is_deposit_or_fee(self, desc: str) -> bool:
        d = desc.upper()
        keywords = [
            "DEPOSIT", "DEP ", "BOTTLE DEP", "CONTAINER", "CRF", "ECO FEE", "ECOFEE",
            "EHF", "ENV FEE", "ENVIRONMENTAL FEE", "BATTERY FEE",
        ]
        return any(k in d for k in keywords)

    def _infer_tax_flag(self, taxcode: str, desc: str) -> Optional[TaxFlag]:
        # Explicit codes
        if taxcode in {"T", "A", "B"}:  # store letters for taxable
            return TaxFlag.TAXABLE
        if taxcode in {"E", "Z"}:
            return TaxFlag.ZERO_RATED

        # Heuristic by description (common zero-rated groceries)
        d = desc.upper()
        zero_keywords = [
            "MILK", "BREAD", "BANANA", "APPLES", "APPLE", "LETTUCE", "CARROT", "EGG", "RICE", "FLOUR",
            "POTATO", "POTATOES", "TOMATO", "TOMATOES", "ONION", "ONIONS", "CUCUMBER",
        ]
        if any(k in d for k in zero_keywords):
            return TaxFlag.ZERO_RATED

        return TaxFlag.TAXABLE  # default in retail context


# Optional: local quick test (paste OCR text to run)
if __name__ == "__main__":
    sample = """
    WALMART SUPERCENTRE
    2025/10/04 14:23
    TC# 1234 5678 9012 34

    GREAT VALUE WHOLE MILK 4L        5.78 E
    BANANAS                          1.20 Z
    GATORADE ORANGE 710ML            1.88 T
    CONTAINER DEPOSIT                0.10

    SUBTOTAL                        8.96
    HST 15%                         1.01
    TOTAL                           9.97
    """
    parser = WalmartCanadaParser()
    print("detect:", parser.detect_format(sample))
    r = parser.parse(sample)
    print("parsed:", r.total, r.subtotal, r.tax_total, len(r.lines))
