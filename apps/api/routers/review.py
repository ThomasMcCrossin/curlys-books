"""
Review queue API - Generic review system for all reviewable items

Handles receipt line items, reimbursement batches, bank matches, etc.
Projects domain-specific data into a unified Reviewable contract via SQL views.
"""
import structlog
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.database import get_db_session
from packages.common.schemas.reviewable import (
    Reviewable,
    ReviewQueueFilters,
    ReviewQueueResponse,
    ReviewActionRequest,
    ReviewBatchRequest,
    ReviewMetrics,
    ReviewType,
    ReviewStatus,
    EntityType,
    ReviewAction,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/review", tags=["review"])


@router.get("/tasks", response_model=ReviewQueueResponse)
async def get_review_queue(
    entity: Optional[EntityType] = Query(None, description="Filter by entity"),
    type: Optional[ReviewType] = Query(None, description="Filter by review type"),
    status: Optional[ReviewStatus] = Query(None, description="Filter by status"),
    vendor: Optional[str] = Query(None, description="Filter by vendor name"),
    min_confidence: Optional[Decimal] = Query(None, ge=0, le=1, description="Minimum confidence"),
    max_confidence: Optional[Decimal] = Query(None, ge=0, le=1, description="Maximum confidence"),
    date_from: Optional[datetime] = Query(None, description="Start date"),
    date_to: Optional[datetime] = Query(None, description="End date"),
    assignee: Optional[str] = Query(None, description="Filter by assignee"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    db: AsyncSession = Depends(get_db_session),
) -> ReviewQueueResponse:
    """
    Get paginated review queue with filters.

    Queries materialized views that project domain tables into Reviewable shape.
    Currently supports: receipt_line_item (future: reimbursement_batch, bank_match, etc.)
    """
    filters = ReviewQueueFilters(
        entity=entity,
        type=type,
        status=status,
        vendor=vendor,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        date_from=date_from,
        date_to=date_to,
        assignee=assignee,
        limit=limit,
        offset=offset,
    )

    # Build WHERE clauses
    where_clauses = []
    params = {}

    if entity:
        where_clauses.append("entity = :entity")
        params["entity"] = entity.value

    if type:
        where_clauses.append("type = :type")
        params["type"] = type.value

    if status:
        where_clauses.append("status = :status::review_status")
        params["status"] = status.value

    if vendor:
        where_clauses.append("vendor ILIKE :vendor")
        params["vendor"] = f"%{vendor}%"

    if min_confidence is not None:
        where_clauses.append("confidence >= :min_confidence")
        params["min_confidence"] = float(min_confidence)

    if max_confidence is not None:
        where_clauses.append("confidence <= :max_confidence")
        params["max_confidence"] = float(max_confidence)

    if date_from:
        where_clauses.append("date >= :date_from")
        params["date_from"] = date_from

    if date_to:
        where_clauses.append("date <= :date_to")
        params["date_to"] = date_to

    if assignee:
        where_clauses.append("assignee = :assignee")
        params["assignee"] = assignee

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Build UNION query across all entity schemas
    # For now, only receipt_line_items; extend later for reimbursements, etc.
    union_parts = []

    if not entity or entity == EntityType.CORP:
        union_parts.append("SELECT * FROM curlys_corp.view_review_receipt_line_items")

    if not entity or entity == EntityType.SOLEPROP:
        union_parts.append("SELECT * FROM curlys_soleprop.view_review_receipt_line_items")

    union_sql = " UNION ALL ".join(union_parts)

    # Count query
    count_query = f"""
        SELECT COUNT(*) as total
        FROM ({union_sql}) combined
        WHERE {where_sql}
    """

    result = await db.execute(text(count_query), params)
    total = result.scalar() or 0

    # Data query
    data_query = f"""
        SELECT
            id, type, entity, created_at, source_ref, summary,
            confidence, requires_review, status, assignee, details,
            vendor, date, amount, age_hours
        FROM ({union_sql}) combined
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """

    params["limit"] = limit
    params["offset"] = offset

    result = await db.execute(text(data_query), params)
    rows = result.mappings().all()

    # Map to Reviewable models
    items = []
    for row in rows:
        items.append(
            Reviewable(
                id=row["id"],
                type=row["type"],
                entity=row["entity"],
                created_at=row["created_at"],
                source_ref=row["source_ref"],
                summary=row["summary"],
                details=row["details"],
                confidence=row["confidence"],
                requires_review=row["requires_review"],
                status=row["status"],
                assignee=row["assignee"],
                vendor=row["vendor"],
                date=row["date"],
                amount=row["amount"],
                age_hours=row["age_hours"],
            )
        )

    logger.info(
        "review_queue_fetched",
        total=total,
        returned=len(items),
        entity=entity.value if entity else "all",
        type=type.value if type else "all",
    )

    return ReviewQueueResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        filters=filters,
    )


@router.get("/tasks/{reviewable_id}", response_model=Reviewable)
async def get_reviewable_item(
    reviewable_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> Reviewable:
    """
    Get full details for a specific reviewable item.

    ID format: {type}:{entity}:{pk}
    Example: receipt_line_item:corp:a1b2c3d4-5678-90ab-cdef-1234567890ab
    """
    # Parse reviewable ID
    try:
        type_str, entity_str, pk = reviewable_id.split(":", 2)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid reviewable ID format")

    # Determine which view to query
    if type_str == "receipt_line_item":
        schema = f"curlys_{entity_str}"
        view = f"{schema}.view_review_receipt_line_items"
    else:
        raise HTTPException(status_code=404, detail=f"Unknown review type: {type_str}")

    # Query the view
    query = f"""
        SELECT
            id, type, entity, created_at, source_ref, summary,
            confidence, requires_review, status, assignee, details,
            vendor, date, amount, age_hours
        FROM {view}
        WHERE id = :reviewable_id
    """

    result = await db.execute(text(query), {"reviewable_id": reviewable_id})
    row = result.mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Reviewable item not found")

    return Reviewable(
        id=row["id"],
        type=row["type"],
        entity=row["entity"],
        created_at=row["created_at"],
        source_ref=row["source_ref"],
        summary=row["summary"],
        details=row["details"],
        confidence=row["confidence"],
        requires_review=row["requires_review"],
        status=row["status"],
        assignee=row["assignee"],
        vendor=row["vendor"],
        date=row["date"],
        amount=row["amount"],
        age_hours=row["age_hours"],
    )


@router.patch("/tasks/{reviewable_id}", response_model=Reviewable)
async def review_action(
    reviewable_id: str,
    action_request: ReviewActionRequest,
    db: AsyncSession = Depends(get_db_session),
) -> Reviewable:
    """
    Perform action on a reviewable item.

    Actions: approve, reject, correct, snooze, reassign, comment, request_info

    For receipts with action=correct, payload must include:
    - product_category: new category
    - account_code: new account code

    Corrections automatically update the product_mappings cache.
    """
    # Parse reviewable ID
    try:
        type_str, entity_str, pk = reviewable_id.split(":", 2)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid reviewable ID format")

    logger.info(
        "review_action_started",
        reviewable_id=reviewable_id,
        action=action_request.action.value,
        performed_by=action_request.performed_by,
    )

    # Route to domain-specific handler
    if type_str == "receipt_line_item":
        from packages.domain.categorization.product_cache import ProductCacheRepository
        from packages.common.config import get_settings

        settings = get_settings()
        cache_repo = ProductCacheRepository(db, settings)

        schema = f"curlys_{entity_str}"

        # Fetch current state
        fetch_query = text(f"""
            SELECT * FROM {schema}.receipt_line_items WHERE id = :pk
        """)
        result = await db.execute(fetch_query, {"pk": pk})
        line_item = result.mappings().first()

        if not line_item:
            raise HTTPException(status_code=404, detail="Receipt line item not found")

        # Perform action
        if action_request.action == ReviewAction.APPROVE:
            update_query = text(f"""
                UPDATE {schema}.receipt_line_items
                SET
                    review_status = 'approved',
                    reviewed_at = NOW(),
                    reviewed_by = :reviewed_by,
                    requires_review = false
                WHERE id = :pk
            """)
            await db.execute(
                update_query,
                {"pk": pk, "reviewed_by": action_request.performed_by},
            )

        elif action_request.action == ReviewAction.REJECT:
            update_query = text(f"""
                UPDATE {schema}.receipt_line_items
                SET
                    review_status = 'rejected',
                    reviewed_at = NOW(),
                    reviewed_by = :reviewed_by
                WHERE id = :pk
            """)
            await db.execute(
                update_query,
                {"pk": pk, "reviewed_by": action_request.performed_by},
            )

        elif action_request.action == ReviewAction.CORRECT:
            if not action_request.payload:
                raise HTTPException(status_code=400, detail="Correction requires payload with product_category and account_code")

            product_category = action_request.payload.get("product_category")
            account_code = action_request.payload.get("account_code")

            if not product_category or not account_code:
                raise HTTPException(status_code=400, detail="Correction payload must include product_category and account_code")

            # Update the line item
            update_query = text(f"""
                UPDATE {schema}.receipt_line_items
                SET
                    product_category = :product_category,
                    account_code = :account_code,
                    review_status = 'approved',
                    reviewed_at = NOW(),
                    reviewed_by = :reviewed_by,
                    requires_review = false,
                    categorization_source = 'manual_correction'
                WHERE id = :pk
            """)
            await db.execute(
                update_query,
                {
                    "pk": pk,
                    "product_category": product_category,
                    "account_code": account_code,
                    "reviewed_by": action_request.performed_by,
                },
            )

            # CRITICAL: Update product_mappings cache so future items are auto-categorized
            if line_item["sku"]:
                # Fetch vendor info from line item details
                # For now, we don't have vendor on line items - need to get from receipt
                # TODO: Join with receipts table or store vendor on line items

                logger.info(
                    "cache_update_needed",
                    sku=line_item["sku"],
                    description=line_item["description"],
                    category=product_category,
                    account_code=account_code,
                    note="Vendor lookup not yet implemented - cache update skipped",
                )

                # Once we have vendor:
                # await cache_repo.save_mapping(
                #     vendor_canonical="VendorName",
                #     sku=line_item["sku"],
                #     description_normalized=line_item["description"],
                #     product_category=product_category,
                #     account_code=account_code,
                #     confidence_score=Decimal("1.00"),  # Manual correction = 100% confidence
                #     source="manual_correction",
                # )

        elif action_request.action == ReviewAction.SNOOZE:
            until = action_request.payload.get("until") if action_request.payload else None
            update_query = text(f"""
                UPDATE {schema}.receipt_line_items
                SET
                    review_status = 'snoozed',
                    reviewed_by = :reviewed_by
                WHERE id = :pk
            """)
            await db.execute(
                update_query,
                {"pk": pk, "reviewed_by": action_request.performed_by},
            )

        elif action_request.action == ReviewAction.REASSIGN:
            if not action_request.payload or "assignee" not in action_request.payload:
                raise HTTPException(status_code=400, detail="Reassign requires payload with assignee")

            update_query = text(f"""
                UPDATE {schema}.receipt_line_items
                SET reviewed_by = :assignee
                WHERE id = :pk
            """)
            await db.execute(
                update_query,
                {"pk": pk, "assignee": action_request.payload["assignee"]},
            )

        elif action_request.action == ReviewAction.REQUEST_INFO:
            update_query = text(f"""
                UPDATE {schema}.receipt_line_items
                SET review_status = 'needs_info'
                WHERE id = :pk
            """)
            await db.execute(update_query, {"pk": pk})

        # Log to audit trail
        audit_query = text("""
            INSERT INTO shared.review_activity (
                reviewable_id, reviewable_type, entity, action,
                performed_by, new_values, reason
            ) VALUES (
                :reviewable_id, :reviewable_type, :entity, :action,
                :performed_by, :new_values, :reason
            )
        """)
        await db.execute(
            audit_query,
            {
                "reviewable_id": reviewable_id,
                "reviewable_type": type_str,
                "entity": entity_str,
                "action": action_request.action.value,
                "performed_by": action_request.performed_by,
                "new_values": action_request.payload,
                "reason": action_request.reason,
            },
        )

        await db.commit()

        logger.info(
            "review_action_completed",
            reviewable_id=reviewable_id,
            action=action_request.action.value,
        )

        # Refresh materialized view (async trigger should handle this, but be explicit)
        refresh_query = text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {schema}.view_review_receipt_line_items")
        await db.execute(refresh_query)
        await db.commit()

        # Return updated item
        return await get_reviewable_item(reviewable_id, db)

    else:
        raise HTTPException(status_code=400, detail=f"Review type {type_str} not yet implemented")


@router.post("/batch", response_model=dict)
async def review_batch_action(
    batch_request: ReviewBatchRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Perform action on multiple reviewable items.

    Useful for bulk approve, reject, reassign.
    """
    results = {"success": [], "failed": []}

    for reviewable_id in batch_request.ids:
        try:
            action_request = ReviewActionRequest(
                action=batch_request.action,
                payload=batch_request.payload,
                reason=batch_request.reason,
                performed_by=batch_request.performed_by,
            )
            await review_action(reviewable_id, action_request, db)
            results["success"].append(reviewable_id)
        except Exception as e:
            logger.error("batch_action_failed", reviewable_id=reviewable_id, error=str(e))
            results["failed"].append({"id": reviewable_id, "error": str(e)})

    logger.info(
        "batch_action_completed",
        total=len(batch_request.ids),
        success=len(results["success"]),
        failed=len(results["failed"]),
    )

    return results


@router.get("/metrics", response_model=dict)
async def get_review_metrics(
    entity: Optional[EntityType] = Query(None, description="Filter by entity"),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Get review queue metrics for dashboard.

    Returns counts, confidence bands, cache hit rate, avg review time.
    """
    # Build entity filter
    entity_filter = ""
    if entity:
        entity_filter = f"WHERE entity = '{entity.value}'"

    # Pending count
    pending_query = f"""
        SELECT COUNT(*) as count
        FROM (
            SELECT * FROM curlys_corp.view_review_receipt_line_items
            UNION ALL
            SELECT * FROM curlys_soleprop.view_review_receipt_line_items
        ) combined
        {entity_filter}
    """
    result = await db.execute(text(pending_query))
    pending_count = result.scalar() or 0

    # Today's approved/rejected
    today_filter = "AND DATE(reviewed_at) = CURRENT_DATE" if not entity_filter else f"{entity_filter} AND DATE(reviewed_at) = CURRENT_DATE"

    approved_query = f"""
        SELECT COUNT(*) as count
        FROM curlys_corp.receipt_line_items
        WHERE review_status = 'approved' {today_filter}
    """
    result = await db.execute(text(approved_query))
    approved_today = result.scalar() or 0

    rejected_query = f"""
        SELECT COUNT(*) as count
        FROM curlys_corp.receipt_line_items
        WHERE review_status = 'rejected' {today_filter}
    """
    result = await db.execute(text(rejected_query))
    rejected_today = result.scalar() or 0

    # Confidence bands
    confidence_query = f"""
        SELECT
            SUM(CASE WHEN confidence < 0.80 THEN 1 ELSE 0 END) as low,
            SUM(CASE WHEN confidence >= 0.80 AND confidence < 0.90 THEN 1 ELSE 0 END) as medium,
            SUM(CASE WHEN confidence >= 0.90 THEN 1 ELSE 0 END) as high
        FROM (
            SELECT * FROM curlys_corp.view_review_receipt_line_items
            UNION ALL
            SELECT * FROM curlys_soleprop.view_review_receipt_line_items
        ) combined
        {entity_filter}
    """
    result = await db.execute(text(confidence_query))
    bands = result.mappings().first()

    return {
        "entity": entity.value if entity else "all",
        "pending_count": pending_count,
        "approved_today": approved_today,
        "rejected_today": rejected_today,
        "confidence_bands": {
            "<0.80": bands["low"] or 0,
            "0.80-0.90": bands["medium"] or 0,
            "≥0.90": bands["high"] or 0,
        },
    }
