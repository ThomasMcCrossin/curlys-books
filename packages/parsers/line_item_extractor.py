class GenericLineItemExtractor:
    def extract_line_items(text: str) -> List[LineItem]:
        # Pattern matching for common receipt formats
        # Regex for: SKU | Description | Qty | Price | Total
        # Handle various layouts