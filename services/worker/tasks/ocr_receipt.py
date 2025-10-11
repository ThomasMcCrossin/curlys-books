"""
OCR receipt processing task - Full implementation

Flow:
1. OCR Strategy (quality data is critical):
   - Images (jpg, png, heic, tiff): AWS Textract ONLY (95%+ confidence)
   - PDFs: Try direct text extraction → Tesseract (≥96%) → Textract fallback
2. Vendor normalization (database lookup)
3. Parser dispatch (route to vendor-specific parser)
4. Line item extraction
5. AI categorization (Phase 1.5)
6. Store results in database

Phase 1.5: AI categorization integrated!
ARCHITECTURE CHANGE: Textract-only for images. PDFs get text extraction → Tesseract (96%+) → Textract.
"""
import os
import shutil
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from uuid import UUID
from decimal import Decimal

import structlog
from celery import Task
from sqlalchemy.ext.asyncio import AsyncSession
from PIL import Image

from services.worker.celery_app import app
from packages.common.database import get_db_session
from packages.common.schemas.receipt_normalized import EntityType
from packages.parsers.ocr_engine import extract_text_from_receipt
from packages.parsers.textract_fallback import extract_with_textract
from packages.parsers.vendor_dispatcher import parse_receipt
from packages.parsers.vendor_service import VendorRegistry
from packages.domain.categorization.categorization_service import categorization_service

logger = structlog.get_logger()

# Storage configuration
RECEIPT_STORAGE_ROOT = os.getenv('RECEIPT_STORAGE_PATH', '/srv/curlys-books/objects')


def match_line_to_bounding_box(line_description: str, bounding_boxes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Find the best matching bounding box for a line item description.

    Simple matching: Find the OCR line that contains the most words from the description.

    Args:
        line_description: Item description from parsed receipt line
        bounding_boxes: List of bounding boxes from Textract with 'text' field

    Returns:
        Best matching bounding box dict, or None if no good match
    """
    if not line_description or not bounding_boxes:
        return None

    # Normalize description for matching
    desc_words = set(line_description.lower().split())

    best_match = None
    best_score = 0

    for bbox in bounding_boxes:
        bbox_text = bbox.get('text', '').lower()
        bbox_words = set(bbox_text.split())

        # Count how many words match
        matches = len(desc_words & bbox_words)

        if matches > best_score:
            best_score = matches
            best_match = bbox

    # Only return if we found at least 2 matching words
    return best_match if best_score >= 2 else None


def create_normalized_image(original_path: str, max_width: int = 800) -> None:
    """
    Create a normalized (resized) version of the receipt image.

    Saves to same directory as `normalized.jpg`.
    Only processes image files (not PDFs).

    Args:
        original_path: Path to original receipt file
        max_width: Maximum width in pixels (default 800)
    """
    original_path = Path(original_path)

    # Only process image files
    if original_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp']:
        try:
            # Load image (with HEIC support via pillow_heif)
            from pillow_heif import register_heif_opener
            register_heif_opener()

            img = Image.open(original_path)

            # Convert to RGB if needed
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')

            # Resize if needed
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

                logger.info("image_normalized",
                           original_size=f"{img.width}x{img.height}",
                           normalized_size=f"{max_width}x{new_height}")

            # Save as normalized.jpg in same directory
            normalized_path = original_path.parent / "normalized.jpg"
            img.save(normalized_path, "JPEG", quality=90, optimize=True)

            logger.info("normalized_image_created",
                       path=str(normalized_path),
                       size_bytes=normalized_path.stat().st_size)
        except Exception as e:
            logger.error("failed_to_create_normalized_image",
                        path=str(original_path),
                        error=str(e),
                        exc_info=True)

# Configuration from environment
TESSERACT_CONFIDENCE_THRESHOLD = float(os.getenv('TESSERACT_CONFIDENCE_THRESHOLD', '0.90'))
TEXTRACT_FALLBACK_ENABLED = os.getenv('TEXTRACT_FALLBACK_ENABLED', 'true').lower() == 'true'


class OCRTask(Task):
    """Base task for OCR with retry logic"""
    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True


@app.task(base=OCRTask, name="services.worker.tasks.ocr_receipt.process_receipt_task")
async def process_receipt_task(
    receipt_id: str,
    entity: str,
    file_path: str,
    content_hash: str,
    source: str,
) -> Dict[str, Any]:
    """
    Process uploaded receipt with OCR and vendor parsing.

    Flow:
    1. OCR with Tesseract (or Textract fallback)
    2. Normalize vendor name
    3. Dispatch to vendor-specific parser
    4. Extract line items
    5. Store in database

    Args:
        receipt_id: UUID of receipt record
        entity: Entity type ("corp" or "soleprop")
        file_path: Full path to receipt file
        content_hash: SHA256 hash of file
        source: Upload source (pwa, email, drive)

    Returns:
        Dict with processing results
    """
    logger.info("ocr_processing_started",
               receipt_id=receipt_id,
               entity=entity,
               file_path=file_path,
               source=source)

    try:
        # Step 1: Extract text with OCR (strategy depends on file type)
        logger.info("ocr_step_1_extracting_text", receipt_id=receipt_id)

        file_ext = Path(file_path).suffix.lower()
        is_image = file_ext in ['.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp']
        is_pdf = file_ext == '.pdf'

        if is_image:
            # Images: Use Textract ONLY (no Tesseract for production)
            logger.info("ocr_using_textract_for_image", receipt_id=receipt_id, file_type=file_ext)

            try:
                ocr_result = await extract_with_textract(file_path)

                logger.info("ocr_textract_complete",
                           receipt_id=receipt_id,
                           confidence=ocr_result.confidence,
                           chars=len(ocr_result.text),
                           method=ocr_result.method)

            except Exception as e:
                logger.error("textract_failed_for_image",
                            receipt_id=receipt_id,
                            error=str(e),
                            exc_info=True)
                raise  # Don't continue with bad OCR - fail fast

        elif is_pdf:
            # PDFs: Try text extraction → Tesseract (96%+) → Textract
            logger.info("ocr_pdf_strategy", receipt_id=receipt_id)

            # First try direct text extraction (free, 100% accurate for text-based PDFs)
            ocr_result = await extract_text_from_receipt(file_path)

            if ocr_result.method == "pdf_text_extraction":
                # Got embedded text - perfect!
                logger.info("ocr_pdf_text_extraction_success",
                           receipt_id=receipt_id,
                           confidence=ocr_result.confidence,
                           chars=len(ocr_result.text))
            else:
                # PDF required OCR (scanned/image-based PDF)
                logger.info("ocr_pdf_required_tesseract",
                           receipt_id=receipt_id,
                           confidence=ocr_result.confidence,
                           chars=len(ocr_result.text),
                           pages=ocr_result.page_count)

                # If Tesseract confidence < 96%, use Textract
                if ocr_result.confidence < 0.96 and TEXTRACT_FALLBACK_ENABLED:
                    logger.warning("ocr_pdf_low_confidence_using_textract",
                                  receipt_id=receipt_id,
                                  tesseract_confidence=ocr_result.confidence,
                                  threshold=0.96)

                    try:
                        ocr_result = await extract_with_textract(file_path)

                        logger.info("ocr_textract_complete",
                                   receipt_id=receipt_id,
                                   confidence=ocr_result.confidence,
                                   chars=len(ocr_result.text))

                    except Exception as e:
                        logger.error("textract_fallback_failed",
                                    receipt_id=receipt_id,
                                    error=str(e),
                                    exc_info=True)
                        # Continue with Tesseract result if Textract fails
                        logger.warning("using_tesseract_despite_low_confidence",
                                      receipt_id=receipt_id,
                                      confidence=ocr_result.confidence)
        else:
            # Unknown file type - try Tesseract as last resort
            logger.warning("ocr_unknown_file_type",
                          receipt_id=receipt_id,
                          file_type=file_ext,
                          message="Attempting Tesseract OCR")
            ocr_result = await extract_text_from_receipt(file_path)

        # Step 1.5: Create normalized image (800px width) for UI display
        logger.info("ocr_step_1_5_creating_normalized_image", receipt_id=receipt_id)
        create_normalized_image(file_path, max_width=800)

        # Step 2: Normalize vendor name and get entity assignment
        logger.info("ocr_step_2_normalizing_vendor", receipt_id=receipt_id)

        vendor_registry = VendorRegistry()
        # Extract vendor from first 500 chars (vendor usually at top)
        vendor_guess = await vendor_registry.extract_vendor_from_text(ocr_result.text[:500])

        if vendor_guess:
            vendor_canonical = await vendor_registry.normalize_vendor_name(vendor_guess)
            # Get typical_entity from vendor_registry
            vendor_entity = await vendor_registry.get_typical_entity(vendor_canonical)

            logger.info("vendor_normalized",
                       receipt_id=receipt_id,
                       vendor_guess=vendor_guess,
                       vendor_canonical=vendor_canonical,
                       typical_entity=vendor_entity)

            # Override entity if vendor has a typical_entity (unless it's 'both')
            if vendor_entity and vendor_entity != 'both':
                if vendor_entity != entity:
                    logger.warning("entity_mismatch",
                                 receipt_id=receipt_id,
                                 uploaded_as=entity,
                                 vendor_typical=vendor_entity,
                                 vendor=vendor_canonical,
                                 message=f"Receipt uploaded as {entity} but {vendor_canonical} typically belongs to {vendor_entity}")
                    # TODO: In production, this should require manual review or reassignment
        else:
            vendor_canonical = None
            logger.warning("vendor_not_detected",
                          receipt_id=receipt_id,
                          text_preview=ocr_result.text[:200])

        # Step 3: Parse receipt with vendor-specific parser
        logger.info("ocr_step_3_parsing_receipt",
                   receipt_id=receipt_id,
                   vendor=vendor_canonical)

        entity_type = EntityType.CORP if entity == 'corp' else EntityType.SOLEPROP

        try:
            parsed_receipt = parse_receipt(ocr_result.text, entity=entity_type)

            logger.info("receipt_parsed",
                       receipt_id=receipt_id,
                       vendor=parsed_receipt.vendor_guess,
                       total=float(parsed_receipt.total),
                       lines=len(parsed_receipt.lines),
                       parser=parsed_receipt.metadata.get('parser'))

        except Exception as e:
            logger.error("parsing_failed",
                        receipt_id=receipt_id,
                        error=str(e),
                        exc_info=True)

            # Return partial result
            return {
                "success": False,
                "receipt_id": receipt_id,
                "error": "parsing_failed",
                "error_message": str(e),
                "ocr_confidence": ocr_result.confidence,
                "ocr_method": ocr_result.method,
                "requires_review": True,
            }

        # Step 3.5: Categorize line items with AI (Phase 1.5)
        logger.info("ocr_step_3_5_categorizing_items",
                   receipt_id=receipt_id,
                   vendor=parsed_receipt.vendor_guess,
                   line_count=len(parsed_receipt.lines))

        categorized_lines = []
        total_ai_cost = Decimal("0")

        async for session in get_db_session():
            try:
                for line in parsed_receipt.lines:
                    # Skip non-item lines (deposits, fees, etc.)
                    if not line.sku and not line.description:
                        categorized_lines.append({
                            "line": line,
                            "categorization": None
                        })
                        continue

                    try:
                        categorization_result = await categorization_service.categorize_line_item(
                            vendor=vendor_canonical or parsed_receipt.vendor_guess or "Unknown",
                            sku=line.sku,
                            raw_description=line.description,
                            line_total=line.line_total or Decimal("0"),
                            db=session
                        )

                        categorized_lines.append({
                            "line": line,
                            "categorization": categorization_result
                        })

                        if categorization_result.ai_cost_usd:
                            total_ai_cost += categorization_result.ai_cost_usd

                        logger.info("line_categorized",
                                   receipt_id=receipt_id,
                                   sku=line.sku,
                                   description=line.description[:50],
                                   category=categorization_result.product_category,
                                   account=categorization_result.account_code,
                                   confidence=float(categorization_result.confidence),
                                   requires_review=categorization_result.requires_review,
                                   source=categorization_result.source)

                    except Exception as e:
                        logger.error("line_categorization_failed",
                                    receipt_id=receipt_id,
                                    sku=line.sku,
                                    description=line.description,
                                    error=str(e),
                                    exc_info=True)

                        # Continue with uncategorized line
                        categorized_lines.append({
                            "line": line,
                            "categorization": None
                        })

                logger.info("categorization_complete",
                           receipt_id=receipt_id,
                           lines_categorized=len([c for c in categorized_lines if c["categorization"]]),
                           lines_failed=len([c for c in categorized_lines if not c["categorization"]]),
                           total_ai_cost=float(total_ai_cost))

                break  # Exit async generator

            except Exception as e:
                logger.error("categorization_batch_failed",
                            receipt_id=receipt_id,
                            error=str(e),
                            exc_info=True)
                # Continue without categorization
                categorized_lines = [{"line": line, "categorization": None} for line in parsed_receipt.lines]
                break

        # Step 4: Reorganize files to readable folder structure
        logger.info("ocr_step_4_reorganizing_files", receipt_id=receipt_id)

        new_file_path = reorganize_receipt_files(
            receipt_id=receipt_id,
            entity=entity,
            vendor=vendor_canonical or parsed_receipt.vendor_guess or "Unknown",
            date=parsed_receipt.purchase_date,
            total=parsed_receipt.total,
            current_path=file_path
        )

        logger.info("files_reorganized",
                   receipt_id=receipt_id,
                   old_path=file_path,
                   new_path=new_file_path)

        # Step 5: Store results in database
        logger.info("ocr_step_5_storing_results", receipt_id=receipt_id)

        async for session in get_db_session():
            try:
                await store_receipt_results(
                    session=session,
                    receipt_id=UUID(receipt_id),
                    entity=entity,
                    ocr_result=ocr_result,
                    parsed_receipt=parsed_receipt,
                    vendor_canonical=vendor_canonical,
                    file_path=new_file_path,
                    categorized_lines=categorized_lines
                )

                await session.commit()

                logger.info("receipt_stored",
                           receipt_id=receipt_id,
                           lines_stored=len(parsed_receipt.lines),
                           lines_categorized=len([c for c in categorized_lines if c["categorization"]]))

                break  # Exit async generator

            except Exception as e:
                await session.rollback()
                logger.error("database_storage_failed",
                            receipt_id=receipt_id,
                            error=str(e),
                            exc_info=True)
                raise

        # Success!
        logger.info("ocr_processing_complete",
                   receipt_id=receipt_id,
                   vendor=parsed_receipt.vendor_guess,
                   total=float(parsed_receipt.total),
                   lines=len(parsed_receipt.lines),
                   ocr_confidence=ocr_result.confidence,
                   ocr_method=ocr_result.method)

        return {
            "success": True,
            "receipt_id": receipt_id,
            "vendor": parsed_receipt.vendor_guess,
            "total": float(parsed_receipt.total),
            "line_count": len(parsed_receipt.lines),
            "ocr_confidence": ocr_result.confidence,
            "ocr_method": ocr_result.method,
            "requires_review": ocr_result.confidence < 0.95 or len(parsed_receipt.lines) == 0,
        }

    except Exception as e:
        logger.error("ocr_processing_failed",
                    receipt_id=receipt_id,
                    error=str(e),
                    exc_info=True)
        raise


def reorganize_receipt_files(
    receipt_id: str,
    entity: str,
    vendor: str,
    date,
    total,
    current_path: str
) -> str:
    """
    Reorganize receipt files into readable folder structure.

    Moves from: /objects/{entity}/{uuid}/original.heic
    To: /objects/{entity}/{vendor}/{date}_{total}/original.heic

    Args:
        receipt_id: Receipt UUID
        entity: Entity type (corp or soleprop)
        vendor: Vendor canonical name
        date: Purchase date
        total: Receipt total (with HST)
        current_path: Current file path

    Returns:
        New file path

    Example:
        /srv/curlys-books/objects/corp/Pepsi/2025-10-07_1381.76/original.heic
    """
    from datetime import date as date_type
    from decimal import Decimal

    # Clean vendor name for folder (remove special characters)
    vendor_clean = "".join(c if c.isalnum() or c in [' ', '-'] else '' for c in vendor)
    vendor_clean = vendor_clean.strip().replace(' ', '-')

    # Format date
    if isinstance(date, date_type):
        date_str = date.strftime('%Y-%m-%d')
    else:
        date_str = str(date) if date else "NODATE"

    # Format total
    if isinstance(total, Decimal):
        total_str = f"{float(total):.2f}"
    else:
        total_str = f"{total:.2f}" if total else "0.00"

    # Build new folder structure: /entity/vendor/date_total/
    folder_name = f"{date_str}_{total_str}"
    new_dir = Path(RECEIPT_STORAGE_ROOT) / entity / vendor_clean / folder_name
    new_dir.mkdir(parents=True, exist_ok=True)

    # Get current file directory and extension
    current_file = Path(current_path)
    ext = current_file.suffix

    # Move all files from old location to new
    old_dir = current_file.parent

    if old_dir.exists():
        for file in old_dir.glob('*'):
            new_file_path = new_dir / file.name
            shutil.move(str(file), str(new_file_path))
            logger.info("file_moved",
                       old=str(file),
                       new=str(new_file_path))

        # Remove old directory
        try:
            old_dir.rmdir()
            logger.info("old_directory_removed", path=str(old_dir))
        except Exception as e:
            logger.warning("failed_to_remove_old_dir", path=str(old_dir), error=str(e))

    # Return new path to original file
    new_file_path = new_dir / f"original{ext}"
    return str(new_file_path)


async def store_receipt_results(
    session: AsyncSession,
    receipt_id: UUID,
    entity: str,
    ocr_result,
    parsed_receipt,
    vendor_canonical: str,
    file_path: str = None,
    categorized_lines: List[Dict[str, Any]] = None
):
    """
    Store OCR and parsing results in database.

    Updates:
    - receipts table (status, vendor, totals, OCR metadata)
    - receipt_line_items table (all line items with categorization)

    Args:
        session: Database session
        receipt_id: Receipt UUID
        entity: Entity type
        ocr_result: OCR extraction result
        parsed_receipt: Parsed receipt object
        vendor_canonical: Normalized vendor name
        file_path: Updated file path (after reorganization)
        categorized_lines: List of dicts with 'line' and 'categorization' keys
    """
    from sqlalchemy import text

    schema_name = f'curlys_{entity}'

    # Update receipts table
    update_fields = {
        "receipt_id": receipt_id,
        "vendor": parsed_receipt.vendor_guess,
        "vendor_canonical": vendor_canonical,
        "total": parsed_receipt.total,
        "ocr_confidence": ocr_result.confidence,
        "ocr_method": ocr_result.method,
        "extracted_text": ocr_result.text[:10000],  # Truncate if too long
        "purchase_date": parsed_receipt.purchase_date,
    }

    # Add file_path if provided
    if file_path:
        update_fields["file_path"] = file_path
        file_path_sql = ", file_path = :file_path"
    else:
        file_path_sql = ""

    await session.execute(
        text(f"""
            UPDATE {schema_name}.receipts
            SET
                status = 'processed',
                vendor_name = :vendor,
                vendor_canonical = :vendor_canonical,
                total_amount = :total,
                ocr_confidence = :ocr_confidence,
                ocr_method = :ocr_method,
                extracted_text = :extracted_text,
                purchase_date = :purchase_date
                {file_path_sql},
                updated_at = NOW()
            WHERE id = :receipt_id
        """),
        update_fields
    )

    # Insert line items with categorization
    if categorized_lines:
        # Phase 1.5: Use categorization data
        for line_num, categorized_line in enumerate(categorized_lines, start=1):
            line = categorized_line["line"]
            categorization = categorized_line.get("categorization")

            if categorization:
                # Find matching bounding box for this line
                bbox = match_line_to_bounding_box(line.description, ocr_result.bounding_boxes)

                # Line was successfully categorized
                await session.execute(
                    text(f"""
                        INSERT INTO {schema_name}.receipt_line_items (
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
                            bounding_box
                        ) VALUES (
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
                            :bounding_box::jsonb
                        )
                    """),
                    {
                        "receipt_id": receipt_id,
                        "line_number": line_num,
                        "sku": line.sku,
                        "description": line.description,
                        "quantity": line.quantity,
                        "unit_price": line.unit_price,
                        "line_total": line.line_total,
                        "account_code": categorization.account_code,
                        "product_category": categorization.product_category,
                        "confidence_score": categorization.confidence,
                        "categorization_source": categorization.source,
                        "requires_review": categorization.requires_review,
                        "ai_cost": categorization.ai_cost_usd,
                        "bounding_box": json.dumps(bbox) if bbox else None,
                    }
                )
            else:
                # Find matching bounding box for this line
                bbox = match_line_to_bounding_box(line.description, ocr_result.bounding_boxes)

                # Line categorization failed, store without categorization
                await session.execute(
                    text(f"""
                        INSERT INTO {schema_name}.receipt_line_items (
                            receipt_id,
                            line_number,
                            sku,
                            description,
                            quantity,
                            unit_price,
                            line_total,
                            requires_review,
                            confidence_score,
                            categorization_source,
                            bounding_box
                        ) VALUES (
                            :receipt_id,
                            :line_number,
                            :sku,
                            :description,
                            :quantity,
                            :unit_price,
                            :line_total,
                            :requires_review,
                            :confidence_score,
                            :categorization_source,
                            :bounding_box::jsonb
                        )
                    """),
                    {
                        "receipt_id": receipt_id,
                        "line_number": line_num,
                        "sku": line.sku,
                        "description": line.description,
                        "quantity": line.quantity,
                        "unit_price": line.unit_price,
                        "line_total": line.line_total,
                        "requires_review": True,  # Needs review since categorization failed
                        "confidence_score": None,
                        "categorization_source": "failed",
                        "bounding_box": json.dumps(bbox) if bbox else None,
                    }
                )
    else:
        # Fallback: No categorization data (should not happen in Phase 1.5+)
        for line_num, line in enumerate(parsed_receipt.lines, start=1):
            # Find matching bounding box for this line
            bbox = match_line_to_bounding_box(line.description, ocr_result.bounding_boxes)

            await session.execute(
                text(f"""
                    INSERT INTO {schema_name}.receipt_line_items (
                        receipt_id,
                        line_number,
                        sku,
                        description,
                        quantity,
                        unit_price,
                        line_total,
                        requires_review,
                        confidence_score,
                        categorization_source,
                        bounding_box
                    ) VALUES (
                        :receipt_id,
                        :line_number,
                        :sku,
                        :description,
                        :quantity,
                        :unit_price,
                        :line_total,
                        :requires_review,
                        :confidence_score,
                        :categorization_source,
                        :bounding_box::jsonb
                    )
                """),
                {
                    "receipt_id": receipt_id,
                    "line_number": line_num,
                    "sku": line.sku,
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "line_total": line.line_total,
                    "requires_review": True,  # All items need review without categorization
                    "confidence_score": None,
                    "categorization_source": "pending",
                    "bounding_box": json.dumps(bbox) if bbox else None,
                }
            )

    logger.info("receipt_results_stored",
               receipt_id=receipt_id,
               vendor=parsed_receipt.vendor_guess,
               lines=len(parsed_receipt.lines))


@app.task(name="services.worker.tasks.ocr_receipt.reprocess_receipt")
async def reprocess_receipt_task(receipt_id: str) -> Dict[str, Any]:
    """
    Reprocess an existing receipt.

    Useful for:
    - Testing new parsers
    - Fixing failed receipts
    - Re-running with improved OCR

    Args:
        receipt_id: UUID of receipt to reprocess

    Returns:
        Processing results
    """
    logger.info("reprocessing_receipt", receipt_id=receipt_id)

    # TODO: Fetch receipt details from database
    # TODO: Call process_receipt_task with existing file_path

    return {
        "success": False,
        "receipt_id": receipt_id,
        "message": "Reprocessing not yet implemented - Phase 1.5",
    }
