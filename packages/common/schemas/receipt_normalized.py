"""
Receipt normalized schema (Pydantic models)
Versioned schema for receipt data interchange
"""
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator


class EntityType(str, Enum):
    """Business entity type"""
    CORP = "corp"
    SOLEPROP = "soleprop"


class ReceiptSource(str, Enum):
    """Source of receipt upload"""
    PWA = "pwa"
    EMAIL = "email"
    DRIVE = "drive"
    MANUAL = "manual"


class ReceiptStatus(str, Enum):
    """Receipt processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    POSTED = "posted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class LineType(str, Enum):
    """Type of line item on receipt"""
    ITEM = "item"
    DISCOUNT = "discount"
    DEPOSIT = "deposit"
    FEE = "fee"
    SUBTOTAL = "subtotal"
    TAX = "tax"
    TOTAL = "total"


class TaxFlag(str, Enum):
    """Tax treatment flag"""
    TAXABLE = "Y"
    ZERO_RATED = "Z"
    EXEMPT = "N"


class ReceiptLine(BaseModel):
    """Single line item on a receipt"""
    line_index: int = Field(..., description="Position in receipt (0-based)")
    line_type: LineType
    raw_text: Optional[str] = Field(None, description="Original OCR text")
    
    # Product identification
    vendor_sku: Optional[str] = Field(None, description="Vendor's SKU/product code")
    upc: Optional[str] = Field(None, description="UPC/barcode if available")
    item_description: Optional[str] = Field(None, description="Human-readable description")
    
    # Quantities and pricing
    quantity: Optional[Decimal] = Field(None, ge=0, description="Quantity purchased")
    unit_price: Optional[Decimal] = Field(None, description="Price per unit")
    line_total: Decimal = Field(..., description="Total for this line")
    
    # Tax information
    tax_flag: Optional[TaxFlag] = Field(None, description="Y=taxable, Z=zero-rated, N=exempt")
    tax_amount: Optional[Decimal] = Field(None, ge=0, description="Tax on this line")
    
    # Mapped GL account (filled by classification engine)
    account_code: Optional[str] = Field(None, description="GL account code")
    
    class Config:
        json_schema_extra = {
            "example": {
                "line_index": 0,
                "line_type": "item",
                "raw_text": "PEPSI 24PK 355ML",
                "vendor_sku": "12345678",
                "item_description": "Pepsi 24-pack 355mL",
                "quantity": 2,
                "unit_price": 8.99,
                "line_total": 17.98,
                "tax_flag": "Y",
                "tax_amount": 2.52,
                "account_code": "5010"
            }
        }


class ReceiptNormalized(BaseModel):
    """
    Normalized receipt data structure (version 1)
    This is the canonical format for all receipts after OCR/parsing
    """
    schema_version: str = Field(default="1.0", description="Schema version for compatibility")
    
    # Identifiers
    receipt_id: Optional[UUID] = Field(None, description="System-generated receipt ID")
    entity: EntityType
    source: ReceiptSource
    
    # Vendor information
    vendor_guess: Optional[str] = Field(None, description="Best guess at vendor name")
    vendor_id: Optional[UUID] = Field(None, description="Matched vendor ID from database")
    
    # Receipt metadata
    purchase_date: date = Field(..., description="Date of purchase")
    invoice_number: Optional[str] = Field(None, description="Vendor invoice/receipt number")
    due_date: Optional[date] = Field(None, description="Payment due date (for bills)")
    
    # Amounts
    currency: str = Field(default="CAD", description="Currency code")
    subtotal: Decimal = Field(..., ge=0, description="Subtotal before tax")
    tax_total: Decimal = Field(default=Decimal(0), ge=0, description="Total tax amount")
    total: Decimal = Field(..., ge=0, description="Grand total")
    
    # Line items
    lines: List[ReceiptLine] = Field(default_factory=list, description="Individual line items")
    
    # Classification hints
    is_bill: bool = Field(default=False, description="True if this is a bill (A/P), False if expense")
    payment_terms: Optional[str] = Field(None, description="e.g., Net 7, Net 14")
    
    # Parsing metadata
    ocr_confidence: Optional[int] = Field(None, ge=0, le=100, description="OCR confidence score")
    ocr_method: Optional[str] = Field(None, description="tesseract, gpt4v, manual")
    parsing_errors: Optional[List[str]] = Field(default=None, description="Any parsing issues")
    
    # File references
    content_hash: Optional[str] = Field(None, description="SHA256 hash of original file")
    perceptual_hash: Optional[str] = Field(None, description="Perceptual hash for similarity")
    
    @validator("total")
    def validate_total(cls, v, values):
        """Ensure total matches subtotal + tax"""
        if "subtotal" in values and "tax_total" in values:
            expected_total = values["subtotal"] + values["tax_total"]
            # Allow small rounding differences (up to 2 cents)
            if abs(v - expected_total) > Decimal("0.02"):
                raise ValueError(
                    f"Total ${v} does not match subtotal ${values['subtotal']} + "
                    f"tax ${values['tax_total']} = ${expected_total}"
                )
        return v
    
    @validator("lines")
    def validate_lines_sum(cls, v, values):
        """Ensure line items sum to subtotal"""
        if not v or "subtotal" not in values:
            return v
        
        items_total = sum(
            line.line_total for line in v 
            if line.line_type in [LineType.ITEM, LineType.FEE]
        )
        discounts_total = sum(
            line.line_total for line in v 
            if line.line_type == LineType.DISCOUNT
        )
        
        calculated_subtotal = items_total - abs(discounts_total)
        
        # Allow small rounding differences
        if abs(calculated_subtotal - values["subtotal"]) > Decimal("0.02"):
            raise ValueError(
                f"Line items sum to ${calculated_subtotal} but subtotal is ${values['subtotal']}"
            )
        
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "schema_version": "1.0",
                "entity": "corp",
                "source": "pwa",
                "vendor_guess": "Costco Wholesale",
                "purchase_date": "2025-01-15",
                "currency": "CAD",
                "subtotal": 156.78,
                "tax_total": 21.95,
                "total": 178.73,
                "lines": [
                    {
                        "line_index": 0,
                        "line_type": "item",
                        "vendor_sku": "1234567",
                        "item_description": "Kirkland Paper Towels 12pk",
                        "quantity": 1,
                        "unit_price": 24.99,
                        "line_total": 24.99,
                        "tax_flag": "Y",
                        "tax_amount": 3.50
                    }
                ],
                "ocr_confidence": 92,
                "ocr_method": "tesseract"
            }
        }


class ReceiptUploadResponse(BaseModel):
    """Response after receipt upload"""
    receipt_id: str
    status: ReceiptStatus
    message: str
    task_id: Optional[str] = Field(None, description="Celery task ID for tracking")


class ReceiptReviewRequest(BaseModel):
    """Request to update receipt after review"""
    approved: bool
    corrections: Optional[ReceiptNormalized] = None
    notes: Optional[str] = None