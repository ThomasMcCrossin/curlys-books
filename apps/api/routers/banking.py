"""
Banking API Router
Handles bank statement import, reconciliation, and matching
"""
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.database import get_db_session
from packages.common.schemas.receipt_normalized import EntityType
from packages.parsers.statement_parser import parse_statement, StatementType

logger = structlog.get_logger()
router = APIRouter()


@router.post("/statements/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_statement(
    file: UploadFile = File(...),
    entity: EntityType = Form(...),
    account_type: str = Form(...),  # checking, savings, credit_card
    db: AsyncSession = Depends(get_db_session),
):
    """
    Upload a bank or credit card statement (CSV format)
    
    - **file**: CSV statement file from CIBC
    - **entity**: corp or soleprop
    - **account_type**: checking, savings, or credit_card
    
    Parses and imports transactions for reconciliation
    """
    logger.info("statement_upload_started",
                filename=file.filename,
                entity=entity.value,
                account_type=account_type)
    
    # Validate file type
    if file.content_type not in ["text/csv", "application/vnd.ms-excel"]:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only CSV files are supported"
        )
    
    # Save temporary file
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        # Parse statement
        result = parse_statement(tmp_path)
        
        logger.info("statement_parsed",
                   statement_type=result.statement_type.value,
                   line_count=len(result.lines),
                   account=result.account_identifier)
        
        # TODO: Save to database
        # - Check for duplicate (file_hash)
        # - Insert statement record
        # - Insert bank_lines
        # - Queue matching task
        
        # Clean up temp file
        Path(tmp_path).unlink()
        
        return {
            "success": True,
            "statement_type": result.statement_type.value,
            "lines_imported": len(result.lines),
            "account": result.account_identifier,
            "file_hash": result.file_hash[:16],
            "message": "Statement imported successfully",
        }
        
    except Exception as e:
        logger.error("statement_import_failed",
                    error=str(e),
                    exc_info=True)
        
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse statement: {str(e)}"
        )


@router.get("/statements")
async def list_statements(
    entity: Optional[EntityType] = None,
    account_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db_session),
):
    """
    List imported bank statements
    """
    # TODO: Implement statement listing
    return {
        "statements": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/transactions/unmatched")
async def list_unmatched_transactions(
    entity: Optional[EntityType] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db_session),
):
    """
    List bank transactions that haven't been matched to receipts
    """
    # TODO: Implement unmatched transaction listing
    return {
        "transactions": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
    }


@router.post("/transactions/{transaction_id}/match")
async def manual_match_transaction(
    transaction_id: str,
    receipt_id: str = Form(...),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Manually match a bank transaction to a receipt
    """
    logger.info("manual_match",
                transaction_id=transaction_id,
                receipt_id=receipt_id)
    
    # TODO: Implement manual matching
    # - Validate transaction and receipt exist
    # - Update match status
    # - Post journal entry
    
    return {
        "success": True,
        "transaction_id": transaction_id,
        "receipt_id": receipt_id,
        "message": "Transaction matched successfully",
    }


@router.post("/transactions/{transaction_id}/classify")
async def classify_transaction(
    transaction_id: str,
    classification: str = Form(...),  # personal, owner_draw, split
    notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Manually classify a bank transaction
    Used for personal transactions, owner draws, etc.
    """
    logger.info("transaction_classified",
                transaction_id=transaction_id,
                classification=classification)
    
    # TODO: Implement classification
    # - Update transaction record
    # - Post appropriate journal entry
    
    return {
        "success": True,
        "transaction_id": transaction_id,
        "classification": classification,
        "message": "Transaction classified",
    }


@router.get("/reconciliation/status")
async def reconciliation_status(
    entity: EntityType,
    account_code: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Get reconciliation status for an account
    Shows matched vs unmatched transactions
    """
    # TODO: Implement reconciliation status
    return {
        "entity": entity.value,
        "account_code": account_code,
        "total_transactions": 0,
        "matched": 0,
        "unmatched": 0,
        "pending_review": 0,
        "match_rate": 0.0,
    }