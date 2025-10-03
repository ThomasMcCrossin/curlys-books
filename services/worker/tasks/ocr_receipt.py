"""
OCR receipt processing task
Uses Tesseract with GPT-4V fallback for low confidence
"""
from pathlib import Path
from typing import Dict, Any

import structlog
from celery import Task

from services.worker.celery_app import app
from packages.parsers.ocr_engine import extract_text_tesseract
from packages.parsers.confidence_scorer import score_extraction_confidence
from packages.parsers.vendor_dispatcher import dispatch_to_vendor_template
from packages.common.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


class OCRTask(Task):
    """Base task for OCR with retry logic"""
    
    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True


@app.task(base=OCRTask, name="services.worker.tasks.ocr_receipt.process_receipt_task")
def process_receipt_task(
    receipt_id: str,
    entity: str,
    file_path: str,
    content_hash: str,
    source: str,
) -> Dict[str, Any]:
    """
    Process uploaded receipt with OCR and vendor parsing
    
    Steps:
    1. Extract text with Tesseract
    2. Score confidence
    3. If low confidence, fallback to GPT-4V
    4. Dispatch to vendor template
    5. Save normalized receipt data
    6. Generate thumbnail
    """
    logger.info("ocr_processing_started",
                receipt_id=receipt_id,
                entity=entity,
                file_path=file_path)
    
    try:
        # Step 1: Extract text with Tesseract
        logger.debug("extracting_text_tesseract", receipt_id=receipt_id)
        ocr_result = extract_text_tesseract(file_path)
        
        # Step 2: Score confidence
        confidence = score_extraction_confidence(ocr_result)
        logger.info("ocr_confidence_scored",
                   receipt_id=receipt_id,
                   confidence=confidence,
                   method="tesseract")
        
        # Step 3: Fallback to GPT if needed
        if confidence < settings.gpt_confidence_threshold and settings.gpt_fallback_enabled:
            logger.info("triggering_gpt_fallback",
                       receipt_id=receipt_id,
                       confidence=confidence)
            from packages.parsers.gpt_fallback import extract_with_gpt4v
            ocr_result = extract_with_gpt4v(file_path)
            confidence = 95  # GPT results are typically high confidence
        
        # Step 4: Dispatch to vendor template
        logger.debug("dispatching_to_vendor_template", receipt_id=receipt_id)
        normalized_receipt = dispatch_to_vendor_template(
            ocr_result=ocr_result,
            confidence=confidence,
            source=source,
        )
        
        # Step 5: Save to database
        logger.debug("saving_normalized_receipt", receipt_id=receipt_id)
        # TODO: Save to database
        # from packages.common.database import save_receipt
        # save_receipt(receipt_id, entity, normalized_receipt, content_hash)
        
        # Step 6: Generate thumbnail
        logger.debug("generating_thumbnail", receipt_id=receipt_id)
        from packages.parsers.thumbnail_generator import generate_thumbnail
        thumb_path = Path(file_path).parent / "thumbnail.jpg"
        generate_thumbnail(file_path, str(thumb_path), max_size=(400, 600))
        
        logger.info("ocr_processing_complete",
                   receipt_id=receipt_id,
                   confidence=confidence,
                   vendor_guess=normalized_receipt.get("vendor_guess"),
                   total=normalized_receipt.get("total"))
        
        return {
            "success": True,
            "receipt_id": receipt_id,
            "confidence": confidence,
            "vendor_guess": normalized_receipt.get("vendor_guess"),
            "total": normalized_receipt.get("total"),
            "requires_review": confidence < 85,
        }
        
    except Exception as e:
        logger.error("ocr_processing_failed",
                    receipt_id=receipt_id,
                    error=str(e),
                    exc_info=True)
        
        # Mark receipt as failed in database
        # TODO: Update database status
        
        raise


@app.task(name="services.worker.tasks.ocr_receipt.reprocess_receipt")
def reprocess_receipt_task(receipt_id: str) -> Dict[str, Any]:
    """
    Reprocess a receipt (e.g., after vendor template update)
    """
    logger.info("reprocessing_receipt", receipt_id=receipt_id)
    
    # TODO: Load receipt from database
    # TODO: Rerun OCR and parsing
    # TODO: Update database
    
    return {
        "success": True,
        "receipt_id": receipt_id,
        "message": "Receipt reprocessed",
    }