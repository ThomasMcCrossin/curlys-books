# packages/parsers/vendor_service.py
"""
Vendor normalization and registry service
"""
from typing import Optional, Dict, List
from dataclasses import dataclass
import structlog
from sqlalchemy import text
from packages.common.database import sessionmanager

logger = structlog.get_logger()


@dataclass
class VendorInfo:
    """Vendor information from registry"""
    canonical_name: str
    vendor_type: str
    default_category: str
    typical_entity: str
    has_line_items: bool
    has_skus: bool
    receipt_format: str
    aliases: List[str]


class VendorRegistry:
    """
    Vendor normalization and lookup service.
    
    Provides:
    - Fuzzy name matching to canonical vendor names
    - Vendor metadata for parsing hints
    - Category suggestions based on vendor type
    """
    
    def __init__(self):
        self._cache: Dict[str, VendorInfo] = {}
    
    async def normalize_vendor_name(self, raw_name: str) -> str:
        """
        Normalize vendor name using fuzzy matching.
        
        Examples:
            "gordon food svc" → "GFS Canada"
            "COSTCO WHSE #123" → "Costco Wholesale"
            "pepsico" → "Pepsi Bottling"
        
        Args:
            raw_name: Raw vendor name from receipt/bank statement
            
        Returns:
            Canonical vendor name or original if no match
        """
        # Check cache first
        cache_key = raw_name.upper().strip()
        if cache_key in self._cache:
            return self._cache[cache_key].canonical_name
        
        # Query database for normalization
        async with sessionmanager.session() as db:
            result = await db.execute(
                text("SELECT normalize_vendor_name(:raw_name) as canonical"),
                {"raw_name": raw_name}
            )
            row = result.fetchone()
            
            if row:
                canonical = row.canonical
                logger.info("vendor_normalized",
                           raw=raw_name,
                           canonical=canonical)
                return canonical
            
            # Return original if no match
            logger.warning("vendor_not_in_registry",
                          raw=raw_name)
            return raw_name
    
    async def get_vendor_info(self, vendor_name: str) -> Optional[VendorInfo]:
        """
        Get vendor metadata from registry.
        
        Args:
            vendor_name: Canonical vendor name or raw name
            
        Returns:
            VendorInfo if found, None otherwise
        """
        # Normalize first
        canonical = await self.normalize_vendor_name(vendor_name)
        
        # Check cache
        if canonical in self._cache:
            return self._cache[canonical]
        
        # Query database
        async with sessionmanager.session() as db:
            result = await db.execute(
                text("""
                    SELECT 
                        canonical_name,
                        vendor_type,
                        default_category,
                        typical_entity,
                        has_line_items,
                        has_skus,
                        receipt_format,
                        aliases
                    FROM vendor_registry
                    WHERE canonical_name = :canonical
                """),
                {"canonical": canonical}
            )
            row = result.fetchone()
            
            if row:
                info = VendorInfo(
                    canonical_name=row.canonical_name,
                    vendor_type=row.vendor_type,
                    default_category=row.default_category,
                    typical_entity=row.typical_entity,
                    has_line_items=row.has_line_items,
                    has_skus=row.has_skus,
                    receipt_format=row.receipt_format,
                    aliases=row.aliases
                )
                
                # Cache it
                self._cache[canonical] = info
                
                return info
        
        return None
    
    async def suggest_category(
        self,
        vendor_name: str,
        entity: str
    ) -> str:
        """
        Suggest account category based on vendor.
        
        Args:
            vendor_name: Vendor name (will be normalized)
            entity: 'corp' or 'soleprop'
            
        Returns:
            Suggested account category
        """
        vendor_info = await self.get_vendor_info(vendor_name)
        
        if vendor_info:
            # Use vendor's default category
            return vendor_info.default_category
        
        # Fallback to generic category
        return "Operating Expenses"
    
    async def get_parser_format(self, vendor_name: str) -> Optional[str]:
        """
        Get receipt format identifier for vendor.
        
        Args:
            vendor_name: Vendor name
            
        Returns:
            Receipt format identifier (e.g., 'gfs_invoice', 'costco_receipt')
        """
        vendor_info = await self.get_vendor_info(vendor_name)
        
        if vendor_info:
            return vendor_info.receipt_format
        
        return None
    
    async def record_transaction(
        self,
        vendor_name: str,
        amount: float,
        transaction_date: str
    ):
        """
        Update vendor statistics when transaction is processed.
        
        Args:
            vendor_name: Vendor name
            amount: Transaction amount
            transaction_date: Date of transaction
        """
        canonical = await self.normalize_vendor_name(vendor_name)

        async with sessionmanager.session() as db:
            await db.execute(
                text("""
                    UPDATE vendor_registry
                    SET last_transaction_date = :date,
                        annual_spend = annual_spend + :amount
                    WHERE canonical_name = :canonical
                """),
                {
                    "canonical": canonical,
                    "amount": amount,
                    "date": transaction_date
                }
            )
            await db.commit()
        
        logger.info("vendor_transaction_recorded",
                   vendor=canonical,
                   amount=amount)


# =====================================================
# USAGE EXAMPLE
# =====================================================

async def example_usage():
    """
    Example of using VendorRegistry in receipt processing.
    """
    registry = VendorRegistry()
    
    # Example 1: Normalize vendor from bank statement
    raw_vendor = "GORDON FOOD SVC"
    canonical = await registry.normalize_vendor_name(raw_vendor)
    print(f"'{raw_vendor}' → '{canonical}'")
    # Output: 'GORDON FOOD SVC' → 'GFS Canada'
    
    # Example 2: Get vendor info
    info = await registry.get_vendor_info("gfs")
    if info:
        print(f"Vendor type: {info.vendor_type}")
        print(f"Has line items: {info.has_line_items}")
        print(f"Receipt format: {info.receipt_format}")
        # Output:
        # Vendor type: food_distributor
        # Has line items: True
        # Receipt format: gfs_invoice
    
    # Example 3: Suggest category
    category = await registry.suggest_category("costco", "corp")
    print(f"Suggested category: {category}")
    # Output: Suggested category: COGS - Inventory
    
    # Example 4: Get parser format
    parser_format = await registry.get_parser_format("Peak Performance")
    print(f"Parser format: {parser_format}")
    # Output: Parser format: peak_invoice


# =====================================================
# INTEGRATION WITH OCR PIPELINE
# =====================================================

class ReceiptProcessor:
    """
    Integration example: Using vendor registry in OCR pipeline.
    """
    
    def __init__(self):
        self.vendor_registry = VendorRegistry()
    
    async def process_receipt(self, ocr_text: str, entity: str) -> Dict:
        """
        Process receipt with vendor normalization.
        
        Steps:
        1. Extract raw vendor name from OCR text
        2. Normalize to canonical name
        3. Get vendor-specific parser
        4. Extract structured data
        5. Suggest categories
        """
        # Step 1: Extract vendor (placeholder - actual implementation depends on OCR)
        raw_vendor = self._extract_vendor_from_text(ocr_text)
        
        # Step 2: Normalize
        canonical_vendor = await self.vendor_registry.normalize_vendor_name(raw_vendor)
        
        logger.info("receipt_vendor_identified",
                   raw=raw_vendor,
                   canonical=canonical_vendor)
        
        # Step 3: Get vendor info
        vendor_info = await self.vendor_registry.get_vendor_info(canonical_vendor)
        
        if not vendor_info:
            logger.warning("vendor_not_in_registry",
                          vendor=canonical_vendor)
            # Use generic parser
            return await self._use_generic_parser(ocr_text, entity)
        
        # Step 4: Check if vendor has custom parser
        if vendor_info.has_line_items:
            # Use vendor-specific parser
            parser = self._get_vendor_parser(vendor_info.receipt_format)
            structured_data = await parser.parse(ocr_text)
        else:
            # Simple total-only parser
            structured_data = await self._parse_simple_total(ocr_text)
        
        # Step 5: Add vendor metadata
        structured_data['vendor'] = canonical_vendor
        structured_data['vendor_type'] = vendor_info.vendor_type
        structured_data['suggested_category'] = vendor_info.default_category
        
        return structured_data
    
    def _extract_vendor_from_text(self, ocr_text: str) -> str:
        """
        Extract vendor name from receipt text.
        Usually in the first few lines.
        """
        # Placeholder - actual implementation in Phase 1
        lines = ocr_text.split('\n')
        return lines[0].strip() if lines else "Unknown"
    
    def _get_vendor_parser(self, format_id: str):
        """
        Get vendor-specific parser based on format ID.
        """
        # Placeholder - will implement in Phase 1
        pass
    
    async def _use_generic_parser(self, text: str, entity: str):
        """Fallback generic parser"""
        # Placeholder
        pass
    
    async def _parse_simple_total(self, text: str):
        """Parse receipts without line items (utilities, services)"""
        # Placeholder
        pass


# =====================================================
# BATCH OPERATIONS
# =====================================================

async def batch_normalize_vendors(raw_vendors: List[str]) -> Dict[str, str]:
    """
    Normalize multiple vendor names at once (useful for bank imports).
    
    Args:
        raw_vendors: List of raw vendor names
        
    Returns:
        Dict mapping raw → canonical names
    """
    registry = VendorRegistry()
    normalized = {}
    
    for raw in raw_vendors:
        canonical = await registry.normalize_vendor_name(raw)
        normalized[raw] = canonical
    
    return normalized


async def audit_vendor_coverage(entity: str = None):
    """
    Analyze vendor coverage in registry.
    Useful for identifying missing vendors.
    """
    query = """
        SELECT 
            vendor_type,
            COUNT(*) as vendor_count,
            SUM(annual_spend) as total_spend,
            COUNT(*) FILTER (WHERE sample_count > 0) as with_samples
        FROM vendor_registry
    """
    
    if entity:
        query += " WHERE typical_entity = :entity OR typical_entity = 'both'"
    
    query += " GROUP BY vendor_type ORDER BY total_spend DESC"

    async with sessionmanager.session() as db:
        result = await db.execute(
            text(query),
            {"entity": entity} if entity else {}
        )
        
        print(f"\n=== Vendor Coverage ({entity or 'All'}) ===")
        for row in result:
            print(f"{row.vendor_type:25} | {row.vendor_count:2} vendors | "
                  f"${row.total_spend:>12,.2f} | {row.with_samples:2} with samples")