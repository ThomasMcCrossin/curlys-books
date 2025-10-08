"""
Vendor-specific receipt/invoice parsers

Each parser handles the unique format of a specific vendor's receipts or invoices.
All parsers inherit from BaseReceiptParser and implement detect_format() and parse().
"""

from packages.parsers.vendors.base_parser import BaseReceiptParser, ParserNotApplicableError, ParserExtractionError
from packages.parsers.vendors.gfs_parser import GFSParser, parse_gfs_invoice
from packages.parsers.vendors.costco_parser import CostcoParser, parse_costco_receipt
from packages.parsers.vendors.grosnor_parser import GrosnorParser, parse_grosnor_invoice
from packages.parsers.vendors.superstore_parser import SuperstoreParser, parse_superstore_receipt
from packages.parsers.vendors.generic_parser import GenericParser, parse_generic_receipt

__all__ = [
    'BaseReceiptParser',
    'ParserNotApplicableError',
    'ParserExtractionError',
    'GFSParser',
    'parse_gfs_invoice',
    'CostcoParser',
    'parse_costco_receipt',
    'GrosnorParser',
    'parse_grosnor_invoice',
    'SuperstoreParser',
    'parse_superstore_receipt',
    'GenericParser',
    'parse_generic_receipt',
]
