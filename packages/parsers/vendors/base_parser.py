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
    ) -> tuple[list[ReceiptLine], Optional[dict]]:
        """
        Detect if line items don't sum to subtotal (faded/missing items).

        IMPORTANT: Does NOT create placeholder lines. Instead, returns a validation
        warning dict that the parser should include in ReceiptNormalized.validation_warnings.

        The review UI will show bounding boxes for detected items so the user
        can visually identify what's missing on the receipt.

        Args:
            lines: List of extracted line items
            subtotal: Receipt subtotal (from footer)
            tolerance: Maximum acceptable difference (default $0.10)
            vendor_name: Vendor name for logging (optional)

        Returns:
            Tuple of (original lines, validation_warning dict or None)
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
                "subtotal_mismatch_detected",
                vendor=vendor_name,
                line_item_total=float(line_item_total),
                subtotal=float(subtotal),
                missing=float(missing_amount),
                message="Line items don't sum to subtotal - receipt flagged for review"
            )

            # Return warning for inclusion in ReceiptNormalized
            warning = {
                "type": "subtotal_mismatch",
                "message": f"Line items sum to ${float(line_item_total):.2f} but receipt subtotal is ${float(subtotal):.2f} (missing ${abs(float(missing_amount)):.2f})",
                "data": {
                    "found_total": float(line_item_total),
                    "expected_total": float(subtotal),
                    "difference": float(abs(missing_amount))
                }
            }
            return lines, warning

        return lines, None


class ParserNotApplicableError(Exception):
    """Raised when a parser's detect_format() returns False but parse() was called anyway"""
    pass


class ParserExtractionError(Exception):
    """Raised when a parser cannot extract required fields from text"""
    pass
