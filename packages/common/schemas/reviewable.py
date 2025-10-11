"""
Reviewable contract - Generic review queue schema

This defines the minimal cross-domain shape the UI knows how to render.
Each domain (receipts, reimbursements, bank matches) projects into this contract.
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class ReviewType(str, Enum):
    """Types of items that can be reviewed"""
    RECEIPT_LINE_ITEM = "receipt_line_item"
    REIMBURSEMENT_BATCH = "reimbursement_batch"
    BANK_MATCH = "bank_match"
    TAX_ALERT = "tax_alert"
    VENDOR_DUPLICATE = "vendor_duplicate"
    MANUAL_ENTRY = "manual_entry"


class ReviewStatus(str, Enum):
    """Review workflow states"""
    PENDING = "pending"
    NEEDS_INFO = "needs_info"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    SNOOZED = "snoozed"


class EntityType(str, Enum):
    """Business entity"""
    CORP = "corp"
    SOLEPROP = "soleprop"


class SourceRef(BaseModel):
    """Back-pointer to source table for audit trail"""
    table: str = Field(..., description="Source table name")
    schema: Optional[str] = Field(None, description="Database schema (curlys_corp, curlys_soleprop)")
    pk: str = Field(..., description="Primary key value")


class Reviewable(BaseModel):
    """
    Generic reviewable item contract

    All review types conform to this shape, with domain-specific
    data in the `details` field.
    """
    # Identity
    id: str = Field(..., description="Globally unique ID: {type}:{entity}:{pk}")
    type: ReviewType = Field(..., description="Type of item to review")
    entity: EntityType = Field(..., description="Business entity (corp or soleprop)")

    # Timestamps
    created_at: datetime = Field(..., description="When item was created")

    # Source reference for audit
    source_ref: SourceRef = Field(..., description="Back-pointer to source record")

    # UI display
    summary: str = Field(..., description="Short description for table view")
    details: Dict[str, Any] = Field(..., description="Domain-specific payload for detail panel")

    # Review metadata
    confidence: Optional[Decimal] = Field(None, ge=0, le=1, description="AI confidence score (if applicable)")
    requires_review: bool = Field(..., description="Gating flag - must be reviewed before posting")
    status: ReviewStatus = Field(..., description="Current review state")
    assignee: Optional[str] = Field(None, description="User assigned to review")

    # Helper fields for filtering/sorting (denormalized from details)
    vendor: Optional[str] = Field(None, description="Vendor name (for receipts)")
    date: Optional[datetime] = Field(None, description="Transaction/purchase date")
    amount: Optional[Decimal] = Field(None, description="Dollar amount")
    age_hours: Optional[Decimal] = Field(None, description="Hours since created")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "receipt_line_item:corp:a1b2c3d4-5678-90ab-cdef-1234567890ab",
                "type": "receipt_line_item",
                "entity": "corp",
                "created_at": "2025-10-10T12:00:00Z",
                "source_ref": {
                    "table": "receipt_line_items",
                    "schema": "curlys_corp",
                    "pk": "a1b2c3d4-5678-90ab-cdef-1234567890ab"
                },
                "summary": "Costco: 'ALANI C&C' → beverage_energy?",
                "details": {
                    "sku": "1868765",
                    "description": "ALANI C&C",
                    "line_total": "142.84",
                    "product_category": "beverage_energy",
                    "account_code": "5015",
                    "confidence": 0.74
                },
                "confidence": 0.74,
                "requires_review": True,
                "status": "pending",
                "vendor": "Costco",
                "amount": 142.84,
                "age_hours": 2.5
            }
        }


class ReviewAction(str, Enum):
    """Actions that can be performed on reviewable items"""
    APPROVE = "approve"
    REJECT = "reject"
    CORRECT = "correct"
    SNOOZE = "snooze"
    REASSIGN = "reassign"
    COMMENT = "comment"
    REQUEST_INFO = "request_info"


class ReviewActionRequest(BaseModel):
    """Request to perform action on a reviewable item"""
    action: ReviewAction = Field(..., description="Action to perform")
    payload: Optional[Dict[str, Any]] = Field(None, description="Action-specific data")
    reason: Optional[str] = Field(None, description="Optional explanation")
    performed_by: Optional[str] = Field(None, description="User performing action")

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "action": "approve",
                    "performed_by": "tom@curlys.ca"
                },
                {
                    "action": "correct",
                    "payload": {
                        "account_code": "5010",
                        "product_category": "beverage_soda"
                    },
                    "reason": "Mountain Dew is soda, not energy drink",
                    "performed_by": "tom@curlys.ca"
                },
                {
                    "action": "snooze",
                    "payload": {
                        "until": "2025-10-15T09:00:00Z"
                    },
                    "reason": "Waiting for vendor clarification",
                    "performed_by": "tom@curlys.ca"
                }
            ]
        }


class ReviewBatchRequest(BaseModel):
    """Bulk action on multiple reviewable items"""
    ids: list[str] = Field(..., description="List of reviewable IDs")
    action: ReviewAction = Field(..., description="Action to perform on all")
    payload: Optional[Dict[str, Any]] = Field(None, description="Action-specific data")
    reason: Optional[str] = Field(None, description="Optional explanation")
    performed_by: Optional[str] = Field(None, description="User performing action")


class ReviewActivity(BaseModel):
    """Audit trail entry for a review action"""
    id: str = Field(..., description="Activity record ID")
    reviewable_id: str = Field(..., description="ID of item that was reviewed")
    reviewable_type: ReviewType = Field(..., description="Type of item")
    entity: EntityType = Field(..., description="Business entity")
    action: str = Field(..., description="Action performed")
    performed_by: Optional[str] = Field(None, description="User who performed action")
    old_values: Optional[Dict[str, Any]] = Field(None, description="State before action")
    new_values: Optional[Dict[str, Any]] = Field(None, description="State after action")
    reason: Optional[str] = Field(None, description="Optional explanation")
    created_at: datetime = Field(..., description="When action was performed")


class ReviewQueueFilters(BaseModel):
    """Filters for review queue queries"""
    entity: Optional[EntityType] = Field(None, description="Filter by entity")
    type: Optional[ReviewType] = Field(None, description="Filter by review type")
    status: Optional[ReviewStatus] = Field(None, description="Filter by status")
    vendor: Optional[str] = Field(None, description="Filter by vendor name")
    min_confidence: Optional[Decimal] = Field(None, ge=0, le=1, description="Minimum confidence")
    max_confidence: Optional[Decimal] = Field(None, ge=0, le=1, description="Maximum confidence")
    date_from: Optional[datetime] = Field(None, description="Start date")
    date_to: Optional[datetime] = Field(None, description="End date")
    assignee: Optional[str] = Field(None, description="Filter by assignee")
    limit: int = Field(50, ge=1, le=200, description="Page size")
    offset: int = Field(0, ge=0, description="Page offset")


class ReviewQueueResponse(BaseModel):
    """Paginated response from review queue"""
    items: list[Reviewable] = Field(..., description="Review items")
    total: int = Field(..., description="Total count (before pagination)")
    limit: int = Field(..., description="Page size")
    offset: int = Field(..., description="Page offset")
    filters: ReviewQueueFilters = Field(..., description="Applied filters")


class ReviewMetrics(BaseModel):
    """Review queue metrics for dashboard"""
    entity: EntityType = Field(..., description="Entity these metrics apply to")
    pending_count: int = Field(..., description="Items awaiting review")
    approved_today: int = Field(..., description="Items approved today")
    rejected_today: int = Field(..., description="Items rejected today")
    avg_review_time_minutes: Optional[Decimal] = Field(None, description="Average time from created to approved/rejected")
    confidence_bands: Dict[str, int] = Field(..., description="Count by confidence range")
    cache_hit_rate: Optional[Decimal] = Field(None, description="% of items resolved from cache")

    class Config:
        json_schema_extra = {
            "example": {
                "entity": "corp",
                "pending_count": 47,
                "approved_today": 12,
                "rejected_today": 2,
                "avg_review_time_minutes": 3.2,
                "confidence_bands": {
                    "<0.80": 15,
                    "0.80-0.90": 20,
                    "≥0.90": 12
                },
                "cache_hit_rate": 0.68
            }
        }
