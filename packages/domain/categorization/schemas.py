"""
Data schemas for categorization module
"""
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class CategorizationSource(str, Enum):
    """Source of categorization decision"""
    CACHE = "cache"           # Found in product_mappings cache
    AI = "ai"                 # AI inference (Claude/GPT)
    USER_OVERRIDE = "user"    # User manually corrected
    RULE = "rule"             # Deterministic rule (e.g., deposits)


class RecognizedItem(BaseModel):
    """
    Result from Stage 1: Item Recognition

    AI expands vendor abbreviations to normalized product names.
    """
    normalized_description: str = Field(..., description="Full product name")
    product_category: Optional[str] = Field(None, description="Product category (e.g., 'beverages_soda')")
    brand: Optional[str] = Field(None, description="Brand name if identified")
    product_type: Optional[str] = Field(None, description="Generic type (e.g., 'soft drink', 'dairy')")

    source: CategorizationSource
    confidence: float = Field(..., ge=0.0, le=1.0, description="AI confidence score")

    # AI cost tracking
    ai_cost_usd: Optional[Decimal] = Field(None, description="Cost of AI call in USD")

    class Config:
        json_schema_extra = {
            "example": {
                "normalized_description": "Mountain Dew Citrus Soda",
                "product_category": "beverages_soda",
                "brand": "Mountain Dew",
                "product_type": "soft drink",
                "source": "ai",
                "confidence": 0.95,
                "ai_cost_usd": 0.0012
            }
        }


class AccountMapping(BaseModel):
    """
    Result from Stage 2: Account Mapping

    Rule-based mapping from product category to GL account.
    """
    account_code: str = Field(..., description="Chart of accounts code")
    account_name: Optional[str] = Field(None, description="Human-readable account name")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Mapping confidence")
    requires_review: bool = Field(default=False, description="Needs manual review")

    mapping_rule: Optional[str] = Field(None, description="Rule that determined this mapping")

    class Config:
        json_schema_extra = {
            "example": {
                "account_code": "5010",
                "account_name": "Cost of Goods Sold - Beverages",
                "confidence": 1.0,
                "requires_review": False,
                "mapping_rule": "beverages_soda → 5010"
            }
        }


class CategorizedLineItem(BaseModel):
    """
    Complete categorization result (Stage 1 + Stage 2)

    This is what gets stored in receipt_line_items table.
    """
    # Original data
    vendor: str
    sku: Optional[str]
    raw_description: str

    # Stage 1: Recognition
    normalized_description: str
    product_category: Optional[str]
    brand: Optional[str]

    # Stage 2: Mapping
    account_code: str
    account_name: Optional[str]

    # Metadata
    source: CategorizationSource
    confidence: float = Field(..., ge=0.0, le=1.0)
    requires_review: bool

    # Cost tracking
    ai_cost_usd: Optional[Decimal] = None

    class Config:
        json_schema_extra = {
            "example": {
                "vendor": "GFS Canada",
                "sku": "1234567",
                "raw_description": "MTN DEW 591ML",
                "normalized_description": "Mountain Dew Citrus Soda 591mL",
                "product_category": "beverages_soda",
                "brand": "Mountain Dew",
                "account_code": "5010",
                "account_name": "Cost of Goods Sold - Beverages",
                "source": "ai",
                "confidence": 0.95,
                "requires_review": False,
                "ai_cost_usd": 0.0012
            }
        }
