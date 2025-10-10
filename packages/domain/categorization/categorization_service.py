"""
Categorization Service - Orchestrates two-stage AI categorization

Flow:
1. Stage 1 (Item Recognition): AI expands abbreviations + classifies category
2. Stage 2 (Account Mapping): Rules map category to GL account

Example:
- Input: "MTN DEW 591ML" from GFS receipt
- Stage 1 (AI): "Mountain Dew Citrus Soda 591mL" → category: beverage_soda
- Stage 2 (Rules): beverage_soda → GL account 5011 (COGS - Beverage - Soda)
- Output: CategorizedLineItem with all fields populated

Caching:
- First GFS receipt with Mountain Dew: AI call (~$0.002)
- Subsequent receipts: Cache hit (FREE)
- After 6 months: 95%+ cache hit rate, <$1/month AI spend
"""
from decimal import Decimal
from typing import Optional, Dict, Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.categorization.item_recognizer import item_recognizer
from packages.domain.categorization.account_mapper import account_mapper
from packages.domain.categorization.schemas import CategorizedLineItem, CategorizationSource

logger = structlog.get_logger()


class CategorizationService:
    """
    Orchestrates two-stage categorization: AI recognition + rule-based mapping.

    Usage:
        service = CategorizationService()
        result = await service.categorize_line_item(
            vendor="GFS Canada",
            sku="1234567",
            raw_description="MTN DEW 591ML",
            line_total=Decimal("24.99"),
            db=db_session
        )
        print(f"Account: {result.account_code}, Category: {result.product_category}")
    """

    def __init__(self):
        """Initialize categorization service with recognizer and mapper."""
        self.recognizer = item_recognizer
        self.mapper = account_mapper

    async def categorize_line_item(
        self,
        vendor: str,
        raw_description: str,
        line_total: Decimal,
        db: AsyncSession,
        sku: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> CategorizedLineItem:
        """
        Categorize a receipt line item using two-stage process.

        Args:
            vendor: Vendor name (e.g., "GFS Canada", "Costco")
            raw_description: Raw description from receipt (e.g., "MTN DEW 591ML")
            line_total: Line item total amount (for equipment capitalization)
            db: Database session for caching
            sku: Vendor SKU code (optional, enables caching)
            context: Additional context (other items, vendor type, etc.)

        Returns:
            CategorizedLineItem with complete categorization
        """
        logger.info("categorization_started",
                   vendor=vendor,
                   sku=sku,
                   description=raw_description)

        # Stage 1: AI Recognition (with caching)
        recognized = await self.recognizer.recognize_item(
            vendor=vendor,
            sku=sku,
            raw_description=raw_description,
            db=db,
            context=context
        )

        logger.info("stage1_complete",
                   vendor=vendor,
                   sku=sku,
                   category=recognized.product_category,
                   source=recognized.source.value,
                   confidence=recognized.confidence)

        # Stage 2: Rule-based GL Account Mapping
        mapping = self.mapper.map_to_account(
            product_category=recognized.product_category,
            line_total=line_total
        )

        logger.info("stage2_complete",
                   vendor=vendor,
                   sku=sku,
                   account_code=mapping.account_code,
                   requires_review=mapping.requires_review)

        # Combine results
        overall_confidence = min(recognized.confidence, mapping.confidence)
        requires_review = mapping.requires_review or recognized.confidence < 0.8

        result = CategorizedLineItem(
            vendor=vendor,
            sku=sku,
            raw_description=raw_description,
            normalized_description=recognized.normalized_description,
            product_category=recognized.product_category,
            brand=recognized.brand,
            account_code=mapping.account_code,
            account_name=mapping.account_name,
            source=recognized.source,
            confidence=overall_confidence,
            requires_review=requires_review,
            ai_cost_usd=recognized.ai_cost_usd
        )

        logger.info("categorization_complete",
                   vendor=vendor,
                   sku=sku,
                   category=result.product_category,
                   account=result.account_code,
                   source=result.source.value,
                   confidence=result.confidence,
                   requires_review=result.requires_review,
                   cost_usd=float(result.ai_cost_usd) if result.ai_cost_usd else 0.0)

        return result

    async def categorize_receipt_lines(
        self,
        vendor: str,
        line_items: list[Dict[str, Any]],
        db: AsyncSession,
    ) -> list[CategorizedLineItem]:
        """
        Categorize all line items from a receipt.

        Processes line items sequentially (could be parallelized in future).

        Args:
            vendor: Vendor name
            line_items: List of line items with fields:
                - raw_description: str
                - line_total: Decimal
                - sku: Optional[str]
            db: Database session

        Returns:
            List of CategorizedLineItem results
        """
        logger.info("batch_categorization_started",
                   vendor=vendor,
                   item_count=len(line_items))

        results = []
        total_cost = Decimal("0")

        # Build context from all items (helps AI understand receipt)
        context = {
            "vendor_type": self._infer_vendor_type(vendor),
            "item_count": len(line_items),
            "other_items": [item.get("raw_description", "") for item in line_items[:10]]  # Sample
        }

        for item in line_items:
            result = await self.categorize_line_item(
                vendor=vendor,
                raw_description=item["raw_description"],
                line_total=item["line_total"],
                db=db,
                sku=item.get("sku"),
                context=context
            )
            results.append(result)

            if result.ai_cost_usd:
                total_cost += result.ai_cost_usd

        cache_hits = sum(1 for r in results if r.source == CategorizationSource.CACHE)
        ai_calls = sum(1 for r in results if r.source == CategorizationSource.AI)

        logger.info("batch_categorization_complete",
                   vendor=vendor,
                   total_items=len(results),
                   cache_hits=cache_hits,
                   ai_calls=ai_calls,
                   total_cost_usd=float(total_cost),
                   avg_cost_per_item=float(total_cost / len(results)) if results else 0.0)

        return results

    def _infer_vendor_type(self, vendor: str) -> str:
        """
        Infer vendor type from vendor name for context.

        Args:
            vendor: Vendor name

        Returns:
            Vendor type description
        """
        vendor_lower = vendor.lower()

        if "gfs" in vendor_lower or "foodservice" in vendor_lower:
            return "food service distributor"
        elif "costco" in vendor_lower or "wholesale" in vendor_lower:
            return "wholesale club"
        elif "superstore" in vendor_lower or "grocery" in vendor_lower:
            return "grocery store"
        elif "pharma" in vendor_lower:
            return "pharmacy"
        elif "pepsi" in vendor_lower or "coke" in vendor_lower:
            return "beverage distributor"
        else:
            return "general vendor"


# Singleton instance
categorization_service = CategorizationService()
