"""
Categorization Module - AI-powered product categorization and GL mapping

Two-stage process:
1. Item Recognition (AI): Expand vendor abbreviations to full product names
2. Account Mapping (Rules): Map product categories to GL accounts

Cache strategy:
- First time seeing a SKU → AI call (~$0.001)
- Subsequent times → Cache hit (free)
- After 6 months: 95%+ cache hit rate

Example flow:
- "SCTSBRN CFF CRM" → AI → "Scotsburn Coffee Cream" → Category: dairy_cream → GL: 5010
- "MTN DEW 591ML" → AI → "Mountain Dew" → Category: beverages_soda → GL: 5010
- "MTN DEW 2L" → AI → "Mountain Dew" → Category: beverages_soda → GL: 5010
  (Different SKUs, but same category → same GL account)
"""

from packages.domain.categorization.account_mapper import (
    AccountMapper,
    AccountMapping,
    ProductCategory,
)
from packages.domain.categorization.schemas import (
    RecognizedItem,
    CategorizedLineItem,
)

__all__ = [
    'AccountMapper',
    'AccountMapping',
    'ProductCategory',
    'RecognizedItem',
    'CategorizedLineItem',
]
