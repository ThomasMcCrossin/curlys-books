"""
CSV Statement Parser for CIBC bank and credit card statements
Handles multiple formats with automatic detection
"""
import csv
import hashlib
import re
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import structlog

logger = structlog.get_logger()


class StatementType(str, Enum):
    """Types of statements we can parse"""
    BANK_ACCOUNT = "bank_account"  # CIBC chequing/savings
    CREDIT_CARD = "credit_card"     # CIBC Visa/Mastercard


@dataclass
class BankLine:
    """Normalized bank/card transaction"""
    transaction_date: datetime
    description: str
    debit: Optional[Decimal]
    credit: Optional[Decimal]
    balance: Optional[Decimal]
    card_last_four: Optional[str] = None
    extracted_merchant: Optional[str] = None
    extracted_reference: Optional[str] = None
    raw_line: Dict = None


@dataclass
class ParsedStatement:
    """Complete parsed statement"""
    statement_type: StatementType
    account_identifier: Optional[str]
    lines: List[BankLine]
    file_hash: str
    metadata: Dict


class CIBCStatementParser:
    """Parse CIBC CSV statements (bank accounts and credit cards)"""
    
    # Known Shopify payout patterns
    SHOPIFY_PATTERNS = [
        r'SHOPIFY',
        r'Shopify-Shopify Inc',
    ]
    
    # Known PAD/autopay patterns
    PAD_PATTERNS = [
        r'MISC PAYMENT',
        r'PRE-AUTHORIZED',
        r'PAD DEBIT',
    ]
    
    # Known payroll patterns
    PAYROLL_PATTERNS = [
        r'E-TRANSFER.*\d{4}\*+\d+',  # E-transfers with masked account numbers
    ]
    
    def __init__(self):
        self.merchant_extractors = [
            self._extract_shopify_payout,
            self._extract_etransfer,
            self._extract_pad_payment,
            self._extract_merchant_location,
        ]
    
    def parse_file(self, file_path: str) -> ParsedStatement:
        """Parse a CSV file and return normalized statement"""
        logger.info("parsing_statement", file_path=file_path)
        
        # Read file and compute hash
        with open(file_path, 'rb') as f:
            content = f.read()
            file_hash = hashlib.sha256(content).hexdigest()
        
        # Read CSV
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        
        if not rows:
            raise ValueError("Empty CSV file")
        
        # Detect format
        statement_type, has_card_column = self._detect_format(rows)
        
        # Parse lines
        lines = []
        for row in rows:
            try:
                line = self._parse_row(row, statement_type, has_card_column)
                if line:
                    lines.append(line)
            except Exception as e:
                logger.warning("failed_to_parse_row", row=row, error=str(e))
                continue
        
        # Extract account identifier
        account_identifier = self._extract_account_identifier(lines, statement_type)
        
        metadata = {
            "row_count": len(rows),
            "parsed_count": len(lines),
            "statement_type": statement_type.value,
        }
        
        logger.info("statement_parsed", 
                   lines=len(lines),
                   statement_type=statement_type.value,
                   file_hash=file_hash[:8])
        
        return ParsedStatement(
            statement_type=statement_type,
            account_identifier=account_identifier,
            lines=lines,
            file_hash=file_hash,
            metadata=metadata
        )
    
    def _detect_format(self, rows: List[List[str]]) -> Tuple[StatementType, bool]:
        """Detect if this is a bank account or credit card statement"""
        if not rows:
            raise ValueError("Cannot detect format from empty file")
        
        # Check column count
        first_row = rows[0]
        col_count = len(first_row)
        
        if col_count == 5:
            # Credit card format: Date, Merchant, Amount, Empty, Card Number
            return StatementType.CREDIT_CARD, True
        elif col_count == 4:
            # Bank account format: Date, Description, Debit, Credit
            return StatementType.BANK_ACCOUNT, False
        else:
            raise ValueError(f"Unknown CSV format with {col_count} columns")
    
    def _parse_row(self, row: List[str], 
                   statement_type: StatementType, 
                   has_card_column: bool) -> Optional[BankLine]:
        """Parse a single CSV row into a BankLine"""
        if len(row) < 3:
            return None
        
        # Parse date (first column)
        try:
            transaction_date = datetime.strptime(row[0].strip(), '%Y-%m-%d')
        except ValueError:
            # Skip header rows or invalid dates
            return None
        
        if statement_type == StatementType.CREDIT_CARD:
            # Credit card format: Date, Merchant, Amount, Empty, Card Number
            description = row[1].strip()
            amount = self._parse_decimal(row[2])
            card_last_four = row[4].strip()[-4:] if len(row) > 4 and row[4] else None
            
            # Credit card: all amounts are debits (charges)
            debit = amount
            credit = None
            balance = None
            
        else:
            # Bank account format: Date, Description, Debit, Credit
            description = row[1].strip()
            debit = self._parse_decimal(row[2])
            credit = self._parse_decimal(row[3])
            balance = None  # CIBC doesn't include running balance in CSV
            card_last_four = None
        
        # Extract merchant and reference information
        merchant, reference = self._extract_merchant_info(description)
        
        return BankLine(
            transaction_date=transaction_date,
            description=description,
            debit=debit,
            credit=credit,
            balance=balance,
            card_last_four=card_last_four,
            extracted_merchant=merchant,
            extracted_reference=reference,
            raw_line={"row": row}
        )
    
    def _parse_decimal(self, value: str) -> Optional[Decimal]:
        """Parse a decimal value, returning None for empty/invalid"""
        if not value or not value.strip():
            return None
        try:
            # Remove any spaces or commas
            cleaned = value.strip().replace(',', '').replace(' ', '')
            return Decimal(cleaned)
        except:
            return None
    
    def _extract_merchant_info(self, description: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract merchant name and reference from description"""
        for extractor in self.merchant_extractors:
            result = extractor(description)
            if result:
                return result
        
        # Default: return full description as merchant
        return description, None
    
    def _extract_shopify_payout(self, description: str) -> Optional[Tuple[str, str]]:
        """Extract Shopify payout information"""
        for pattern in self.SHOPIFY_PATTERNS:
            if re.search(pattern, description, re.IGNORECASE):
                return "Shopify", "payout"
        return None
    
    def _extract_etransfer(self, description: str) -> Optional[Tuple[str, str]]:
        """Extract e-transfer information (payroll, reimbursements)"""
        match = re.search(r'E-TRANSFER\s*(\d+)\s+(.+?)\s+(\d{4}\*+\d+)', description, re.IGNORECASE)
        if match:
            transfer_id = match.group(1)
            recipient = match.group(2).strip()
            masked_account = match.group(3)
            return recipient, f"etransfer-{transfer_id}"
        return None
    
    def _extract_pad_payment(self, description: str) -> Optional[Tuple[str, str]]:
        """Extract PAD/autopay payment information"""
        for pattern in self.PAD_PATTERNS:
            if re.search(pattern, description, re.IGNORECASE):
                # Try to extract vendor name after the PAD indicator
                match = re.search(r'(?:MISC PAYMENT|PRE-AUTHORIZED)\s+(.+?)(?:\s+\d|$)', description, re.IGNORECASE)
                if match:
                    vendor = match.group(1).strip()
                    return vendor, "pad"
        return None
    
    def _extract_merchant_location(self, description: str) -> Optional[Tuple[str, str]]:
        """Extract merchant name and location from description"""
        # Pattern: "MERCHANT NAME LOCATION, PROVINCE"
        # Examples: "PC EXPRESS 0312 AMHERST, NS"
        #           "DISNEY PLUS 1 800727-1800, CA"
        match = re.match(r'([A-Z][A-Z\s\d]+?)(?:\s+\d{3,})?(?:\s+(.+?),\s*([A-Z]{2}))?$', description)
        if match:
            merchant = match.group(1).strip()
            location = match.group(2).strip() if match.group(2) else None
            province = match.group(3) if match.group(3) else None
            
            # Clean up merchant name
            merchant = re.sub(r'\s+\d{4,}.*$', '', merchant)  # Remove trailing numbers/phones
            
            if location:
                return merchant, f"{location}, {province}"
            return merchant, province
        
        return None
    
    def _extract_account_identifier(self, lines: List[BankLine], 
                                    statement_type: StatementType) -> Optional[str]:
        """Extract account identifier from transactions"""
        if statement_type == StatementType.CREDIT_CARD:
            # Use most common card number
            card_numbers = [line.card_last_four for line in lines if line.card_last_four]
            if card_numbers:
                from collections import Counter
                most_common = Counter(card_numbers).most_common(1)[0][0]
                return f"****{most_common}"
        
        # For bank accounts, we don't have the account number in the CSV
        # Could be inferred from filenames or user input
        return None


def parse_statement(file_path: str) -> ParsedStatement:
    """Convenience function to parse a statement file"""
    parser = CIBCStatementParser()
    return parser.parse_file(file_path)


# Example usage
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python statement_parser.py <csv_file>")
        sys.exit(1)
    
    result = parse_statement(sys.argv[1])
    
    print(f"\nStatement Type: {result.statement_type.value}")
    print(f"Account: {result.account_identifier or 'Unknown'}")
    print(f"Total Lines: {len(result.lines)}")
    print(f"File Hash: {result.file_hash[:16]}...")
    print("\nFirst 5 transactions:")
    for line in result.lines[:5]:
        amount = line.debit or line.credit or Decimal(0)
        direction = "DR" if line.debit else "CR"
        print(f"  {line.transaction_date.date()} | {line.extracted_merchant or line.description[:40]:40} | {direction} ${amount:>10.2f}")