"""
Vendor Dispatcher - Routes OCR text to appropriate vendor parser

Flow:
1. Try each registered parser's detect_format() method
2. Use first parser that returns True
3. Fall back to GenericParser if no match

Priority order (highest annual spend first):
1. Grosnor Distribution ($65K)
2. Costco Wholesale ($47K)
3. GFS Canada ($41K)
4. [More vendors as implemented]
"""

from typing import Optional
import structlog

from packages.common.schemas.receipt_normalized import ReceiptNormalized, EntityType
from packages.parsers.vendors.base_parser import BaseReceiptParser
from packages.parsers.vendors.gfs_parser import GFSParser
from packages.parsers.vendors.costco_parser import CostcoParser
from packages.parsers.vendors.grosnor_parser import GrosnorParser
from packages.parsers.vendors.superstore_parser import SuperstoreParser
from packages.parsers.vendors.pepsi_parser import PepsiParser
from packages.parsers.vendors.pharmasave_parser import PharmasaveParser
from packages.parsers.vendors.generic_parser import GenericParser

logger = structlog.get_logger()


class VendorDispatcher:
    """
    Intelligently routes OCR text to the correct vendor parser.

    Uses detect_format() to identify vendor, then calls appropriate parser.
    Falls back to generic parser for unknown vendors.
    """

    def __init__(self):
        """
        Initialize dispatcher with all available parsers.

        Order matters - parsers are tried in registration order.
        Put highest-spend vendors first for performance.
        Generic parser always goes last (fallback).
        """
        self.parsers: list[BaseReceiptParser] = [
            # Priority order by annual spend
            GrosnorParser(),      # $65.4K - Sole Prop collectibles
            CostcoParser(),       # $47.4K - Both entities
            GFSParser(),          # $40.6K - Corp food service
            PepsiParser(),        # Pepsi Beverages - Corp
            SuperstoreParser(),   # Atlantic Superstore
            PharmasaveParser(),   # MacQuarries Pharmasave - Corp
            # GenericParser MUST be last - it always matches
            GenericParser(),      # Fallback for unknown vendors
        ]

        logger.info("vendor_dispatcher_initialized", parser_count=len(self.parsers))

    def dispatch(self, ocr_text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
        """
        Parse receipt by dispatching to appropriate vendor parser.

        Args:
            ocr_text: Raw OCR text from receipt/invoice
            entity: Entity type (corp or soleprop)

        Returns:
            ReceiptNormalized object

        Raises:
            ValueError: If no parser can handle the text
        """
        logger.info("dispatch_started", text_length=len(ocr_text), entity=entity.value)

        # Try each parser's detect_format() method
        for parser in self.parsers:
            parser_name = parser.__class__.__name__

            try:
                if parser.detect_format(ocr_text):
                    logger.info("parser_matched", parser=parser_name)
                    result = parser.parse(ocr_text, entity)

                    # Validate result
                    if not result:
                        logger.warning("parser_returned_none", parser=parser_name)
                        continue

                    logger.info("parse_success",
                               parser=parser_name,
                               vendor=result.vendor_guess,
                               total=float(result.total),
                               lines=len(result.lines))

                    return result

            except Exception as e:
                logger.warning("parser_failed",
                             parser=parser_name,
                             error=str(e),
                             exc_info=True)
                # Continue to next parser
                continue

        # Should never reach here since GenericParser always returns True
        logger.error("no_parser_matched_critical", text_preview=ocr_text[:200])
        raise ValueError("CRITICAL: No parser matched (Generic parser should have caught this)")

    def detect_vendor(self, ocr_text: str) -> Optional[str]:
        """
        Identify vendor without parsing full receipt.

        Useful for:
        - Vendor normalization before parsing
        - Routing decisions
        - Analytics

        Args:
            ocr_text: Raw OCR text

        Returns:
            Parser class name that would handle this, or None
        """
        for parser in self.parsers:
            try:
                if parser.detect_format(ocr_text):
                    return parser.__class__.__name__
            except Exception:
                continue
        return None

    def list_parsers(self) -> list[str]:
        """
        Get list of available parser names.

        Returns:
            List of parser class names
        """
        return [p.__class__.__name__ for p in self.parsers]


# Singleton instance for easy import
dispatcher = VendorDispatcher()


def parse_receipt(ocr_text: str, entity: EntityType = EntityType.CORP) -> ReceiptNormalized:
    """
    Convenience function to parse receipt with auto-detection.

    Args:
        ocr_text: Raw OCR text from receipt/invoice
        entity: Entity type (corp or soleprop)

    Returns:
        ReceiptNormalized object

    Example:
        ```python
        from packages.parsers.vendor_dispatcher import parse_receipt
        from packages.common.schemas.receipt_normalized import EntityType

        receipt = parse_receipt(ocr_text, entity=EntityType.CORP)
        print(f"Vendor: {receipt.vendor_guess}")
        print(f"Total: ${receipt.total}")
        ```
    """
    return dispatcher.dispatch(ocr_text, entity)
