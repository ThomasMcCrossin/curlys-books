"""
OCR receipt processing task - Full implementation

Flow:
1. Tesseract OCR (primary, fast)
2. Textract fallback if confidence < 90%
3. Vendor normalization (database lookup)
4. Parser dispatch (route to vendor-specific parser)
5. Line item extraction
6. Store results in database

Phase 1 Complete!
"""
import os
from typing import Dict, Any
from uuid import UUID

import structlog
from celery import Task
from sqlalchemy.ext.asyncio import AsyncSession

from services.worker.celery_app import app
from packages.common.database import get_db_session
from packages.common.schemas.receipt_normalized import EntityType
from packages.parsers.ocr_engine import extract_text_from_receipt
from packages.parsers.textract_fallback import extract_with_textract
from packages.parsers.vendor_dispatcher import parse_receipt
from packages.parsers.vendor_service import VendorRegistry

logger = structlog.get_logger()

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
        # Step 1: Extract text with OCR
        logger.info("ocr_step_1_extracting_text", receipt_id=receipt_id)

        # Try Tesseract first (fast, free)
        ocr_result = await extract_text_from_receipt(file_path)

        logger.info("ocr_tesseract_complete",
                   receipt_id=receipt_id,
                   confidence=ocr_result.confidence,
                   method=ocr_result.method,
                   chars=len(ocr_result.text),
                   pages=ocr_result.page_count)

        # Fallback to Textract if confidence too low
        if ocr_result.confidence < TESSERACT_CONFIDENCE_THRESHOLD and TEXTRACT_FALLBACK_ENABLED:
            logger.warning("ocr_low_confidence_fallback_to_textract",
                          receipt_id=receipt_id,
                          tesseract_confidence=ocr_result.confidence,
                          threshold=TESSERACT_CONFIDENCE_THRESHOLD)

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
                # Continue with Tesseract result even if Textract fails
                logger.info("using_tesseract_despite_low_confidence",
                           receipt_id=receipt_id)

        # Step 2: Normalize vendor name
        logger.info("ocr_step_2_normalizing_vendor", receipt_id=receipt_id)

        vendor_registry = VendorRegistry()
        # Extract vendor from first 500 chars (vendor usually at top)
        vendor_guess = await vendor_registry.extract_vendor_from_text(ocr_result.text[:500])

        if vendor_guess:
            vendor_canonical = await vendor_registry.normalize_vendor_name(vendor_guess)
            logger.info("vendor_normalized",
                       receipt_id=receipt_id,
                       vendor_guess=vendor_guess,
                       vendor_canonical=vendor_canonical)
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

        # Step 4: Store results in database
        logger.info("ocr_step_4_storing_results", receipt_id=receipt_id)

        async for session in get_db_session():
            try:
                await store_receipt_results(
                    session=session,
                    receipt_id=UUID(receipt_id),
                    entity=entity,
                    ocr_result=ocr_result,
                    parsed_receipt=parsed_receipt,
                    vendor_canonical=vendor_canonical
                )

                await session.commit()

                logger.info("receipt_stored",
                           receipt_id=receipt_id,
                           lines_stored=len(parsed_receipt.lines))

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


async def store_receipt_results(
    session: AsyncSession,
    receipt_id: UUID,
    entity: str,
    ocr_result,
    parsed_receipt,
    vendor_canonical: str
):
    """
    Store OCR and parsing results in database.

    Updates:
    - receipts table (status, vendor, totals, OCR metadata)
    - receipt_line_items table (all line items)

    Args:
        session: Database session
        receipt_id: Receipt UUID
        entity: Entity type
        ocr_result: OCR extraction result
        parsed_receipt: Parsed receipt object
        vendor_canonical: Normalized vendor name
    """
    from sqlalchemy import text

    schema_name = f'curlys_{entity}'

    # Update receipts table
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
                purchase_date = :purchase_date,
                updated_at = NOW()
            WHERE id = :receipt_id
        """),
        {
            "receipt_id": receipt_id,
            "vendor": parsed_receipt.vendor_guess,
            "vendor_canonical": vendor_canonical,
            "total": parsed_receipt.total,
            "ocr_confidence": ocr_result.confidence,
            "ocr_method": ocr_result.method,
            "extracted_text": ocr_result.text[:10000],  # Truncate if too long
            "purchase_date": parsed_receipt.date,
        }
    )

    # Insert line items
    for line_num, line in enumerate(parsed_receipt.lines, start=1):
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
                    categorization_source
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
                    :categorization_source
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
                "requires_review": True,  # Phase 1: All items need review (no AI categorization yet)
                "confidence_score": ocr_result.confidence,
                "categorization_source": "pending",  # Will be set when AI categorization is implemented
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
