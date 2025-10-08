## Example: Costco Parser Implementation

```python
# packages/parsers/vendors/costco_parser.py

import re
from decimal import Decimal
from typing import List
from .base_parser import BaseReceiptParser, LineItem

class CostcoParser(BaseReceiptParser):
    """Parser for Costco warehouse receipts"""
    
    # Format indicators
    VENDOR_INDICATORS = [
        'COSTCO',
        'COSTCO WHOLESALE',
        'MONCTON #1345'
    ]
    
    # Patterns
    LINE_PATTERN = re.compile(
        r'(\d{5,7})\s+(.*?)\s+(\d+\.\d{2})\s+([YN])',
        re.MULTILINE
    )
    
    DEPOSIT_PATTERN = re.compile(
        r'(\d{4})\s+DEPOSIT/(\d+)\s+(\d+\.\d{2})'
    )
    
    DISCOUNT_PATTERN = re.compile(
        r'(\d+)\s+TPD/(.*?)\s+(\d+\.\d{2})-'
    )
    
    def detect_format(self, text: str) -> bool:
        """Check if this is a Costco receipt"""
        text_upper = text.upper()
        return any(ind in text_upper for ind in self.VENDOR_INDICATORS)
    
    def parse_line_items(self, text: str) -> List[LineItem]:
        """Extract line items from Costco receipt"""
        items = []
        
        # Parse main line items
        for match in self.LINE_PATTERN.finditer(text):
            sku = match.group(1)
            description = match.group(2).strip()
            price = Decimal(match.group(3))
            taxable = match.group(4) == 'Y'
            
            items.append(LineItem(
                sku=sku,
                description=description,
                line_total=price,
                raw_line=match.group(0)
            ))
        
        # Parse deposits (separate line items)
        for match in self.DEPOSIT_PATTERN.finditer(text):
            items.append(LineItem(
                sku=None,
                description=f"Deposit - {match.group(2)}",
                line_total=Decimal(match.group(3)),
                raw_line=match.group(0)
            ))
        
        # Parse discounts (negative line items)
        for match in self.DISCOUNT_PATTERN.finditer(text):
            items.append(LineItem(
                sku=match.group(1),
                description=f"Discount - {match.group(2)}",
                line_total=-Decimal(match.group(3)),
                raw_line=match.group(0)
            ))
        
        return items