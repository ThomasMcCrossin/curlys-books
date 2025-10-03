"""
Receipts API Router
Handles receipt upload, review, approval, and querying
"""
import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from packages.common.database import get_db_session
from packages.common.config import get_settings
from packages.common.schemas.receipt_normalized import ReceiptUploadResponse, ReceiptStatus, EntityType
from services.worker.tasks.ocr_receipt import process_receipt_task

logger = structlog.get_logger()
router = APIRouter()
settings = get_settings()


@router.post("/upload", response_model=ReceiptUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_receipt(
    file: UploadFile = File(...),
    entity: EntityType = Form(...),
    source: str = Form(default="pwa"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Upload a receipt for processing
    
    - **file**: Receipt image (JPG, PNG, HEIC) or PDF
    - **entity**: corp or soleprop
    - **source**: pwa, email, drive, or manual
    
    Returns a receipt ID and queues OCR processing
    """
    logger.info("receipt_upload_started",
                filename=file.filename,
                content_type=file.content_type,
                entity=entity.value,
                source=source)
    
    # Validate file type
    allowed_types = [
        "image/jpeg",
        "image/png", 
        "image/heic",
        "application/pdf",
    ]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type {file.content_type} not supported. Allowed: {allowed_types}"
        )
    
    # Read file content
    content = await file.read()
    
    # Compute content hash for deduplication
    content_hash = hashlib.sha256(content).hexdigest()
    
    # Check for duplicate
    # TODO: Query database for existing receipt with same content_hash
    # For now, just log
    logger.debug("checking_duplicate", content_hash=content_hash[:16])
    
    # Generate receipt ID
    receipt_id = str(uuid.uuid4())
    
    # Determine file extension
    ext = Path(file.filename).suffix if file.filename else ".jpg"
    if not ext:
        ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/heic": ".heic",
            "application/pdf": ".pdf",
        }.get(file.content_type, ".bin")
    
    # Save original file to storage
    entity_storage = Path(settings.receipt_storage_path) / entity.value / receipt_id
    entity_storage.mkdir(parents=True, exist_ok=True)
    
    original_path = entity_storage / f"original{ext}"
    with open(original_path, "wb") as f:
        f.write(content)
    
    logger.info("receipt_saved",
                receipt_id=receipt_id,
                path=str(original_path),
                size_bytes=len(content))
    
    # Queue OCR processing task
    task = process_receipt_task.delay(
        receipt_id=receipt_id,
        entity=entity.value,
        file_path=str(original_path),
        content_hash=content_hash,
        source=source,
    )
    
    logger.info("receipt_queued_for_processing",
                receipt_id=receipt_id,
                task_id=task.id)
    
    return ReceiptUploadResponse(
        receipt_id=receipt_id,
        status=ReceiptStatus.PENDING,
        message="Receipt uploaded and queued for processing",
        task_id=task.id,
    )


@router.get("/{receipt_id}")
async def get_receipt(
    receipt_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Get receipt details by ID
    """
    # TODO: Query database for receipt
    # For now, return stub
    return {
        "receipt_id": receipt_id,
        "status": "pending",
        "message": "Receipt lookup not yet implemented",
    }


@router.get("/")
async def list_receipts(
    entity: Optional[EntityType] = None,
    status: Optional[ReceiptStatus] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db_session),
):
    """
    List receipts with optional filters
    """
    # TODO: Implement receipt listing
    return {
        "receipts": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
    }


@router.post("/{receipt_id}/approve")
async def approve_receipt(
    receipt_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Approve a receipt and post to general ledger
    """
    # TODO: Implement approval workflow
    logger.info("receipt_approved", receipt_id=receipt_id)
    return {
        "receipt_id": receipt_id,
        "status": "approved",
        "message": "Receipt approved and posted to GL",
    }


@router.post("/{receipt_id}/reject")
async def reject_receipt(
    receipt_id: str,
    reason: str = Form(...),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Reject a receipt (mark as void or duplicate)
    """
    logger.info("receipt_rejected", receipt_id=receipt_id, reason=reason)
    return {
        "receipt_id": receipt_id,
        "status": "rejected",
        "reason": reason,
    }


@router.get("/{receipt_id}/file")
async def get_receipt_file(
    receipt_id: str,
    file_type: str = "original",  # original, thumbnail, normalized
):
    """
    Retrieve receipt file (image or PDF)
    """
    # TODO: Implement file retrieval
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="File retrieval not yet implemented",
    )