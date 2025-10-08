"""
Receipt Repository - Entity-aware database operations for receipts

CRITICAL: All database writes/reads must route to correct schema based on entity.

Schema routing:
- EntityType.CORP → curlys_corp.receipt_line_items
- EntityType.SOLEPROP → curlys_soleprop.receipt_line_items
- Shared tables → shared.product_mappings, shared.vendor_registry

This ensures complete separation between Corp (Canteen) and Sole Prop (Sports Store).
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.schemas.receipt_normalized import (
    ReceiptNormalized,
    ReceiptLine,
    EntityType,
    LineType,
    TaxFlag,
)

logger = structlog.get_logger()


class ReceiptRepository:
    """
    Entity-aware repository for receipt database operations.

    All methods accept entity parameter and route to correct schema.
    """

    @staticmethod
    def _get_schema_name(entity: EntityType) -> str:
        """Get schema name for entity"""
        return "curlys_corp" if entity == EntityType.CORP else "curlys_soleprop"

    async def save_receipt_line_items(
        self,
        receipt_id: UUID,
        entity: EntityType,
        lines: List[ReceiptLine],
        db: AsyncSession,
    ) -> int:
        """
        Save receipt line items to entity-specific schema.

        Args:
            receipt_id: Receipt UUID
            entity: Corp or Sole Prop
            lines: List of parsed line items
            db: Database session

        Returns:
            Number of lines inserted
        """
        schema_name = self._get_schema_name(entity)

        logger.info("saving_receipt_lines",
                   receipt_id=str(receipt_id),
                   entity=entity.value,
                   schema=schema_name,
                   line_count=len(lines))

        # Build INSERT query
        query = text(f"""
            INSERT INTO {schema_name}.receipt_line_items (
                id,
                receipt_id,
                line_number,
                sku,
                description,
                quantity,
                unit_price,
                line_total,
                account_code,
                product_category,
                confidence_score,
                categorization_source,
                requires_review,
                ai_cost,
                created_at
            ) VALUES (
                :id,
                :receipt_id,
                :line_number,
                :sku,
                :description,
                :quantity,
                :unit_price,
                :line_total,
                :account_code,
                :product_category,
                :confidence_score,
                :categorization_source,
                :requires_review,
                :ai_cost,
                :created_at
            )
        """)

        inserted = 0
        for line in lines:
            try:
                await db.execute(query, {
                    "id": uuid4(),
                    "receipt_id": receipt_id,
                    "line_number": line.line_index,
                    "sku": line.vendor_sku,
                    "description": line.item_description or line.raw_text or "Unknown",
                    "quantity": float(line.quantity) if line.quantity else 1.0,
                    "unit_price": float(line.unit_price) if line.unit_price else None,
                    "line_total": float(line.line_total),
                    "account_code": line.account_code,
                    "product_category": None,  # Will be set by AI categorization
                    "confidence_score": None,
                    "categorization_source": "parser",  # From vendor parser
                    "requires_review": True,  # Default to requiring review
                    "ai_cost": None,
                    "created_at": datetime.utcnow(),
                })
                inserted += 1
            except Exception as e:
                logger.error("line_insert_failed",
                           line_index=line.line_index,
                           error=str(e),
                           exc_info=True)
                # Continue with other lines
                continue

        await db.commit()

        logger.info("receipt_lines_saved",
                   receipt_id=str(receipt_id),
                   entity=entity.value,
                   inserted=inserted,
                   total=len(lines))

        return inserted

    async def get_receipt_line_items(
        self,
        receipt_id: UUID,
        entity: EntityType,
        db: AsyncSession,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve receipt line items from entity-specific schema.

        Args:
            receipt_id: Receipt UUID
            entity: Corp or Sole Prop
            db: Database session

        Returns:
            List of line items as dictionaries
        """
        schema_name = self._get_schema_name(entity)

        query = text(f"""
            SELECT
                id,
                receipt_id,
                line_number,
                sku,
                description,
                quantity,
                unit_price,
                line_total,
                account_code,
                product_category,
                confidence_score,
                categorization_source,
                requires_review,
                reviewed_at,
                reviewed_by,
                ai_cost,
                created_at
            FROM {schema_name}.receipt_line_items
            WHERE receipt_id = :receipt_id
            ORDER BY line_number
        """)

        result = await db.execute(query, {"receipt_id": receipt_id})
        rows = result.fetchall()

        logger.info("receipt_lines_retrieved",
                   receipt_id=str(receipt_id),
                   entity=entity.value,
                   count=len(rows))

        return [dict(row._mapping) for row in rows]

    async def update_line_categorization(
        self,
        line_id: UUID,
        entity: EntityType,
        account_code: str,
        product_category: Optional[str],
        confidence_score: Optional[Decimal],
        categorization_source: str,
        ai_cost: Optional[Decimal],
        db: AsyncSession,
    ) -> bool:
        """
        Update line item categorization (from AI or user override).

        Args:
            line_id: Line item UUID
            entity: Corp or Sole Prop
            account_code: GL account code
            product_category: Product classification
            confidence_score: AI confidence (0-1)
            categorization_source: 'cached', 'ai_suggested', 'user_override'
            ai_cost: Cost in USD if AI was used
            db: Database session

        Returns:
            True if updated successfully
        """
        schema_name = self._get_schema_name(entity)

        query = text(f"""
            UPDATE {schema_name}.receipt_line_items
            SET
                account_code = :account_code,
                product_category = :product_category,
                confidence_score = :confidence_score,
                categorization_source = :categorization_source,
                ai_cost = :ai_cost
            WHERE id = :line_id
        """)

        result = await db.execute(query, {
            "line_id": line_id,
            "account_code": account_code,
            "product_category": product_category,
            "confidence_score": float(confidence_score) if confidence_score else None,
            "categorization_source": categorization_source,
            "ai_cost": float(ai_cost) if ai_cost else None,
        })

        await db.commit()

        updated = result.rowcount > 0

        logger.info("line_categorization_updated",
                   line_id=str(line_id),
                   entity=entity.value,
                   account_code=account_code,
                   source=categorization_source,
                   updated=updated)

        return updated

    async def mark_line_reviewed(
        self,
        line_id: UUID,
        entity: EntityType,
        reviewed_by: str,
        db: AsyncSession,
    ) -> bool:
        """
        Mark line item as reviewed and approved.

        Args:
            line_id: Line item UUID
            entity: Corp or Sole Prop
            reviewed_by: Username/email of reviewer
            db: Database session

        Returns:
            True if marked successfully
        """
        schema_name = self._get_schema_name(entity)

        query = text(f"""
            UPDATE {schema_name}.receipt_line_items
            SET
                requires_review = false,
                reviewed_at = :reviewed_at,
                reviewed_by = :reviewed_by
            WHERE id = :line_id
        """)

        result = await db.execute(query, {
            "line_id": line_id,
            "reviewed_at": datetime.utcnow(),
            "reviewed_by": reviewed_by,
        })

        await db.commit()

        logger.info("line_marked_reviewed",
                   line_id=str(line_id),
                   entity=entity.value,
                   reviewed_by=reviewed_by)

        return result.rowcount > 0

    async def get_lines_requiring_review(
        self,
        entity: EntityType,
        db: AsyncSession,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get line items requiring manual review for an entity.

        Args:
            entity: Corp or Sole Prop
            limit: Max items to return
            db: Database session

        Returns:
            List of line items needing review
        """
        schema_name = self._get_schema_name(entity)

        query = text(f"""
            SELECT
                id,
                receipt_id,
                line_number,
                sku,
                description,
                quantity,
                line_total,
                account_code,
                product_category,
                confidence_score,
                categorization_source,
                created_at
            FROM {schema_name}.receipt_line_items
            WHERE requires_review = true
            ORDER BY created_at DESC
            LIMIT :limit
        """)

        result = await db.execute(query, {"limit": limit})
        rows = result.fetchall()

        logger.info("review_queue_retrieved",
                   entity=entity.value,
                   count=len(rows))

        return [dict(row._mapping) for row in rows]

    async def get_line_items_by_sku(
        self,
        entity: EntityType,
        vendor_canonical: str,
        sku: str,
        db: AsyncSession,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get historical line items for a specific vendor SKU.

        Useful for:
        - Checking how this SKU was categorized before
        - Learning from past decisions
        - Consistency checking

        Args:
            entity: Corp or Sole Prop
            vendor_canonical: Normalized vendor name
            sku: Vendor SKU code
            limit: Max items to return
            db: Database session

        Returns:
            List of historical line items for this SKU
        """
        schema_name = self._get_schema_name(entity)

        query = text(f"""
            SELECT
                id,
                receipt_id,
                line_number,
                sku,
                description,
                account_code,
                product_category,
                confidence_score,
                categorization_source,
                reviewed_at,
                created_at
            FROM {schema_name}.receipt_line_items
            WHERE sku = :sku
            ORDER BY created_at DESC
            LIMIT :limit
        """)

        result = await db.execute(query, {
            "sku": sku,
            "limit": limit,
        })
        rows = result.fetchall()

        logger.debug("sku_history_retrieved",
                    entity=entity.value,
                    sku=sku,
                    count=len(rows))

        return [dict(row._mapping) for row in rows]


# Singleton instance
receipt_repository = ReceiptRepository()
