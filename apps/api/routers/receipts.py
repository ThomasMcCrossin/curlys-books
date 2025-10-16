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
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from packages.common.database import get_db_session
from packages.common.config import get_settings
from packages.common.schemas.receipt_normalized import ReceiptUploadResponse, ReceiptStatus, EntityType
from apps.api.tasks import queue_receipt_ocr

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
    
    # Queue OCR processing
    task_id = queue_receipt_ocr(
        receipt_id=receipt_id,
        entity=entity.value,
        file_path=str(original_path),
        content_hash=content_hash,
        source=source
    )

    
    logger.info("receipt_queued_for_processing",
                receipt_id=receipt_id,
                task_id=task_id)
    
    return ReceiptUploadResponse(
         receipt_id=receipt_id,
         status=ReceiptStatus.PENDING,
         message="Receipt uploaded and queued for processing",
         task_id=task_id,
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
    file_type: str = Query("original", description="File type: original, thumbnail, normalized, or cropped"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Retrieve receipt file (image or PDF)

    File types:
    - original: Original uploaded file
    - thumbnail: Web-optimized preview (if available)
    - normalized: Preprocessed for OCR (if available)
    - cropped: Automatically cropped to receipt bounds using Textract bounding boxes (removes background)
    """
    from fastapi.responses import FileResponse, StreamingResponse
    import os
    import io
    import json
    from PIL import Image
    from pillow_heif import register_heif_opener

    # Register HEIF support
    register_heif_opener()

    # Query database to get receipt info and bounding boxes
    from sqlalchemy import text

    # Try both entity schemas
    receipt = None
    schema_name = None
    for schema in ["curlys_corp", "curlys_soleprop"]:
        query = text(f"SELECT id, entity, original_file_path FROM {schema}.receipts WHERE id = :receipt_id")
        result = await db.execute(query, {"receipt_id": receipt_id})
        receipt = result.mappings().first()

        if receipt:
            schema_name = schema
            break

    if not receipt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Receipt {receipt_id} not found",
        )

    logger.info("receipt_file_requested",
               receipt_id=receipt_id,
               file_type=file_type,
               entity=receipt['entity'])

    # Determine file path based on file_type
    receipt_dir = Path(f"/srv/curlys-books/objects/{receipt['entity']}/{receipt_id}")

    if file_type == "original":
        # Check if file exists in proper storage location
        if receipt_dir.exists():
            # Prefer browser-compatible formats (JPG, PNG) over HEIC/HEIF
            for ext in [".jpg", ".jpeg", ".png", ".heic", ".heif", ".pdf"]:
                candidate = receipt_dir / f"original{ext}"
                if candidate.exists():
                    file_path = candidate
                    break
            else:
                # Fallback to original_file_path from database
                file_path = Path(receipt["original_file_path"])
        else:
            # Fallback to original_file_path from database
            file_path = Path(receipt["original_file_path"])

    elif file_type == "thumbnail":
        file_path = receipt_dir / "thumbnail.jpg"
    elif file_type == "normalized":
        file_path = receipt_dir / "normalized.jpg"
        logger.info("looking_for_normalized",
                   receipt_id=receipt_id,
                   path=str(file_path),
                   exists=file_path.exists())
    elif file_type == "cropped":
        # Check for cached cropped version
        cropped_path = receipt_dir / "cropped.jpg"
        if cropped_path.exists():
            logger.info("using_cached_cropped_image", receipt_id=receipt_id)
            return FileResponse(
                path=str(cropped_path),
                media_type="image/jpeg",
                filename=f"{receipt_id}_cropped.jpg",
            )

        # Need to create cropped version on-the-fly
        # First, get all bounding boxes for this receipt
        bbox_query = text(f"""
            SELECT bounding_box
            FROM {schema_name}.receipt_line_items
            WHERE receipt_id = :receipt_id
            AND bounding_box IS NOT NULL
        """)
        bbox_result = await db.execute(bbox_query, {"receipt_id": receipt_id})
        bounding_boxes = [row[0] for row in bbox_result.fetchall() if row[0]]

        if not bounding_boxes:
            # No bounding boxes available, fall back to normalized
            logger.warning("no_bounding_boxes_available", receipt_id=receipt_id)
            file_path = receipt_dir / "normalized.jpg"
            if not file_path.exists():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No bounding box data available and normalized image not found"
                )
        else:
            # Calculate overall bounding box (union of all line bounding boxes)
            # Find the min/max coordinates across all boxes
            min_left = min(float(bbox.get('left', 1)) for bbox in bounding_boxes)
            min_top = min(float(bbox.get('top', 1)) for bbox in bounding_boxes)
            max_right = max(float(bbox.get('left', 0)) + float(bbox.get('width', 0)) for bbox in bounding_boxes)
            max_bottom = max(float(bbox.get('top', 0)) + float(bbox.get('height', 0)) for bbox in bounding_boxes)

            # Add 5% padding around the detected content
            padding = 0.05
            min_left = max(0, min_left - padding)
            min_top = max(0, min_top - padding)
            max_right = min(1, max_right + padding)
            max_bottom = min(1, max_bottom + padding)

            logger.info("calculated_crop_bounds",
                       receipt_id=receipt_id,
                       left=min_left,
                       top=min_top,
                       right=max_right,
                       bottom=max_bottom,
                       bbox_count=len(bounding_boxes))

            # Load the normalized image (or original if normalized doesn't exist)
            source_path = receipt_dir / "normalized.jpg"
            if not source_path.exists():
                # Try original
                for ext in [".jpg", ".jpeg", ".png", ".heic", ".heif"]:
                    candidate = receipt_dir / f"original{ext}"
                    if candidate.exists():
                        source_path = candidate
                        break
                else:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="No source image found for cropping"
                    )

            # Load and crop the image
            img = Image.open(source_path)
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')

            width, height = img.size
            crop_box = (
                int(min_left * width),
                int(min_top * height),
                int(max_right * width),
                int(max_bottom * height)
            )

            cropped_img = img.crop(crop_box)

            # Save to cache
            cropped_img.save(cropped_path, "JPEG", quality=90, optimize=True)

            logger.info("cropped_image_created",
                       receipt_id=receipt_id,
                       original_size=f"{width}x{height}",
                       cropped_size=f"{cropped_img.width}x{cropped_img.height}",
                       cached_path=str(cropped_path))

            # Return the cropped image
            return FileResponse(
                path=str(cropped_path),
                media_type="image/jpeg",
                filename=f"{receipt_id}_cropped.jpg",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file_type: {file_type}",
        )

    # Check if file exists
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {file_type} at {file_path}",
        )

    # Determine media type based on extension
    ext = file_path.suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".pdf": "application/pdf",
    }
    media_type = media_type_map.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=f"{receipt_id}_{file_type}{ext}",
    )