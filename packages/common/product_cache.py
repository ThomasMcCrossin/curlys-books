"""
Product Mapping Cache - Cross-entity SKU categorization caching

The product_mappings table is in the SHARED schema because:
- Same vendor SKU means same product regardless of entity
- Reduces AI costs by sharing learnings
- Example: GFS SKU "1234567" (Pepsi) is ALWAYS beverages, Corp or Sole Prop

Cache Strategy:
1. First time seeing SKU → Call AI → User approves → Cache it
2. Next time (any entity) → Cache hit → Free & instant
3. After 6 months: 95%+ cache hit rate, <$1/month AI costs

Entity tracking:
- times_seen increments for each entity independently
- Different entities may use same SKU different ways (edge case)
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any
from uuid import uuid4
import hashlib

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class ProductCacheRepository:
    """
    Repository for product mapping cache operations.

    Cache is in shared schema - cross-entity to maximize hit rate.
    """

    @staticmethod
    def _generate_lookup_hash(vendor_canonical: str, sku: str) -> str:
        """Generate hash for fast lookups"""
        key = f"{vendor_canonical}||{sku}"
        return hashlib.sha256(key.encode()).hexdigest()

    async def get_cached_categorization(
        self,
        vendor_canonical: str,
        sku: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        """
        Look up cached categorization for vendor SKU.

        Args:
            vendor_canonical: Normalized vendor name (e.g., "GFS Canada")
            sku: Vendor SKU code
            db: Database session

        Returns:
            Cached categorization dict or None if not found
        """
        lookup_hash = self._generate_lookup_hash(vendor_canonical, sku)

        query = text("""
            SELECT
                id,
                vendor_canonical,
                sku,
                description_normalized,
                account_code,
                product_category,
                times_seen,
                user_confidence,
                last_seen,
                created_at
            FROM shared.product_mappings
            WHERE lookup_hash = :lookup_hash
        """)

        result = await db.execute(query, {"lookup_hash": lookup_hash})
        row = result.fetchone()

        if row:
            logger.debug("cache_hit",
                        vendor=vendor_canonical,
                        sku=sku,
                        account_code=row.account_code,
                        times_seen=row.times_seen)

            return dict(row._mapping)
        else:
            logger.debug("cache_miss",
                        vendor=vendor_canonical,
                        sku=sku)
            return None

    async def cache_categorization(
        self,
        vendor_canonical: str,
        sku: str,
        description: str,
        account_code: str,
        product_category: Optional[str],
        user_confidence: Optional[Decimal],
        db: AsyncSession,
    ) -> bool:
        """
        Store categorization in cache.

        Args:
            vendor_canonical: Normalized vendor name
            sku: Vendor SKU code
            description: Normalized product description
            account_code: GL account code
            product_category: Product classification
            user_confidence: User confidence rating (0-1)
            db: Database session

        Returns:
            True if cached successfully
        """
        lookup_hash = self._generate_lookup_hash(vendor_canonical, sku)

        # Check if already exists (update times_seen)
        existing = await self.get_cached_categorization(vendor_canonical, sku, db)

        if existing:
            # Update existing entry
            query = text("""
                UPDATE shared.product_mappings
                SET
                    times_seen = times_seen + 1,
                    last_seen = :last_seen,
                    updated_at = :updated_at
                WHERE lookup_hash = :lookup_hash
            """)

            await db.execute(query, {
                "lookup_hash": lookup_hash,
                "last_seen": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            })

            logger.info("cache_updated",
                       vendor=vendor_canonical,
                       sku=sku,
                       times_seen=existing['times_seen'] + 1)
        else:
            # Insert new entry
            query = text("""
                INSERT INTO shared.product_mappings (
                    id,
                    vendor_canonical,
                    sku,
                    description_normalized,
                    account_code,
                    product_category,
                    times_seen,
                    user_confidence,
                    last_seen,
                    lookup_hash,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :vendor_canonical,
                    :sku,
                    :description,
                    :account_code,
                    :product_category,
                    :times_seen,
                    :user_confidence,
                    :last_seen,
                    :lookup_hash,
                    :created_at,
                    :updated_at
                )
            """)

            await db.execute(query, {
                "id": uuid4(),
                "vendor_canonical": vendor_canonical,
                "sku": sku,
                "description": description,
                "account_code": account_code,
                "product_category": product_category,
                "times_seen": 1,
                "user_confidence": float(user_confidence) if user_confidence else None,
                "last_seen": datetime.utcnow(),
                "lookup_hash": lookup_hash,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            })

            logger.info("cache_created",
                       vendor=vendor_canonical,
                       sku=sku,
                       account_code=account_code)

        await db.commit()
        return True

    async def update_cache_confidence(
        self,
        vendor_canonical: str,
        sku: str,
        user_confidence: Decimal,
        db: AsyncSession,
    ) -> bool:
        """
        Update user confidence rating for cached item.

        Args:
            vendor_canonical: Normalized vendor name
            sku: Vendor SKU code
            user_confidence: New confidence rating (0-1)
            db: Database session

        Returns:
            True if updated successfully
        """
        lookup_hash = self._generate_lookup_hash(vendor_canonical, sku)

        query = text("""
            UPDATE shared.product_mappings
            SET
                user_confidence = :user_confidence,
                updated_at = :updated_at
            WHERE lookup_hash = :lookup_hash
        """)

        result = await db.execute(query, {
            "lookup_hash": lookup_hash,
            "user_confidence": float(user_confidence),
            "updated_at": datetime.utcnow(),
        })

        await db.commit()

        updated = result.rowcount > 0

        logger.info("cache_confidence_updated",
                   vendor=vendor_canonical,
                   sku=sku,
                   confidence=float(user_confidence),
                   updated=updated)

        return updated

    async def get_cache_stats(self, db: AsyncSession) -> Dict[str, Any]:
        """
        Get cache statistics for monitoring.

        Returns:
            Dictionary with cache metrics
        """
        query = text("""
            SELECT
                COUNT(*) as total_skus,
                SUM(times_seen) as total_lookups,
                AVG(times_seen) as avg_lookups_per_sku,
                COUNT(CASE WHEN times_seen = 1 THEN 1 END) as single_use_skus,
                COUNT(CASE WHEN times_seen > 10 THEN 1 END) as frequent_skus
            FROM shared.product_mappings
        """)

        result = await db.execute(query)
        row = result.fetchone()

        stats = dict(row._mapping)

        # Calculate cache hit rate (rough estimate)
        # Assumption: First lookup is miss, subsequent are hits
        total_lookups = stats['total_lookups'] or 0
        total_skus = stats['total_skus'] or 0

        if total_lookups > 0:
            cache_misses = total_skus
            cache_hits = total_lookups - cache_misses
            hit_rate = (cache_hits / total_lookups) * 100
        else:
            hit_rate = 0

        stats['estimated_hit_rate_pct'] = round(hit_rate, 2)

        logger.info("cache_stats_retrieved", **stats)

        return stats

    async def get_top_products(
        self,
        db: AsyncSession,
        limit: int = 20,
    ) -> list[Dict[str, Any]]:
        """
        Get most frequently seen products (for analytics).

        Args:
            limit: Number of products to return
            db: Database session

        Returns:
            List of top products with usage counts
        """
        query = text("""
            SELECT
                vendor_canonical,
                sku,
                description_normalized,
                account_code,
                product_category,
                times_seen,
                last_seen
            FROM shared.product_mappings
            ORDER BY times_seen DESC
            LIMIT :limit
        """)

        result = await db.execute(query, {"limit": limit})
        rows = result.fetchall()

        return [dict(row._mapping) for row in rows]


# Singleton instance
product_cache = ProductCacheRepository()
