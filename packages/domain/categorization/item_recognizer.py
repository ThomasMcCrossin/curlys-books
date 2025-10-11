"""
Item Recognizer - AI-powered product recognition and categorization

Stage 1 of categorization: Uses Claude API to expand vendor abbreviations
and classify products into detailed categories.

Caching Strategy:
- First time seeing vendor+SKU → AI call (~$0.001-0.003 per item)
- Subsequent times → Cache hit from product_mappings table (FREE)
- After 6 months: 95%+ cache hit rate

Example:
- Input: vendor="GFS Canada", sku="1234567", desc="MTN DEW 591ML"
- AI Output: "Mountain Dew Citrus Soda 591mL" → category: "beverage_soda"
- Cache: Store vendor+SKU → category mapping
- Next time: Cache hit, no AI call needed
"""
import os
from decimal import Decimal
from typing import Optional, List, Dict, Any

import anthropic
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.product_cache import product_cache
from packages.domain.categorization.schemas import (
    RecognizedItem,
    CategorizationSource,
)
from packages.domain.categorization.account_mapper import ProductCategory
from packages.domain.categorization.product_lookup import product_lookup

logger = structlog.get_logger()


class ItemRecognizer:
    """
    AI-powered product recognition with caching.

    Uses Anthropic Claude API for vendor abbreviation expansion
    and product categorization.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize item recognizer.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            logger.warning("anthropic_api_key_missing",
                          message="ANTHROPIC_API_KEY not set, AI recognition will fail")

        self.client = anthropic.AsyncAnthropic(api_key=self.api_key) if self.api_key else None

        # Cost per token (Claude Sonnet 4.5 pricing as of 2025)
        self.input_cost_per_1k = Decimal("0.003")   # $3 per 1M input tokens
        self.output_cost_per_1k = Decimal("0.015")  # $15 per 1M output tokens

    async def recognize_item(
        self,
        vendor: str,
        sku: Optional[str],
        raw_description: str,
        db: AsyncSession,
        context: Optional[Dict[str, Any]] = None,
    ) -> RecognizedItem:
        """
        Recognize and categorize a product from receipt line item.

        Args:
            vendor: Vendor name (e.g., "GFS Canada", "Costco")
            sku: Vendor SKU code (if available)
            raw_description: Raw description from receipt (e.g., "MTN DEW 591ML")
            db: Database session for caching
            context: Optional context (other items on receipt, vendor type, etc.)

        Returns:
            RecognizedItem with normalized description and category
        """
        # Step 1: Check cache first
        if sku:
            cached = await product_cache.get_cached_categorization(vendor, sku, db)
            if cached:
                logger.info("cache_hit",
                           vendor=vendor,
                           sku=sku,
                           category=cached['product_category'],
                           times_seen=cached['times_seen'])

                return RecognizedItem(
                    normalized_description=cached['description_normalized'],
                    product_category=cached['product_category'],
                    brand=None,  # Not stored in cache currently
                    product_type=None,
                    source=CategorizationSource.CACHE,
                    confidence=1.0,  # Cache is 100% confidence
                    ai_cost_usd=None  # Free!
                )

        # Step 2: Cache miss - call AI
        logger.info("cache_miss",
                   vendor=vendor,
                   sku=sku,
                   raw_description=raw_description,
                   message="Calling AI for recognition")

        if not self.client:
            logger.error("ai_client_not_initialized",
                        message="Cannot call AI without API key")
            # Return unknown category
            return RecognizedItem(
                normalized_description=raw_description,
                product_category=ProductCategory.UNKNOWN.value,
                brand=None,
                product_type=None,
                source=CategorizationSource.AI,
                confidence=0.0,
                ai_cost_usd=None
            )

        # Step 2.5: Try to look up product on vendor website (if SKU available)
        product_info = None
        if sku:
            product_info = await product_lookup.lookup_product(
                vendor=vendor,
                sku=sku,
                raw_description=raw_description
            )

            if product_info:
                # Add product info to context
                if context is None:
                    context = {}
                context["web_lookup"] = product_info
                logger.info("web_lookup_found",
                           vendor=vendor,
                           sku=sku,
                           product_name=product_info.get("product_name"))

        # Build AI prompt
        prompt = self._build_recognition_prompt(
            vendor=vendor,
            raw_description=raw_description,
            context=context
        )

        # Call Claude API
        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-5",  # Claude Sonnet 4.5 (better reasoning for ambiguous items)
                max_tokens=1024,
                temperature=0.0,  # Deterministic for consistency
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            # Calculate cost
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost = self._calculate_cost(input_tokens, output_tokens)

            logger.info("ai_recognition_complete",
                       vendor=vendor,
                       sku=sku,
                       input_tokens=input_tokens,
                       output_tokens=output_tokens,
                       cost_usd=float(cost))

            # Parse AI response
            result = self._parse_ai_response(response.content[0].text, raw_description)
            result.ai_cost_usd = cost
            result.source = CategorizationSource.AI

            # Cache the result (if we have SKU)
            if sku and result.product_category != ProductCategory.UNKNOWN.value:
                await product_cache.cache_categorization(
                    vendor_canonical=vendor,
                    sku=sku,
                    description=result.normalized_description,
                    account_code="",  # Will be filled by account_mapper
                    product_category=result.product_category,
                    user_confidence=Decimal(str(result.confidence)),
                    db=db
                )

            return result

        except Exception as e:
            logger.error("ai_recognition_failed",
                        vendor=vendor,
                        sku=sku,
                        error=str(e),
                        exc_info=True)

            # Return unknown on error
            return RecognizedItem(
                normalized_description=raw_description,
                product_category=ProductCategory.UNKNOWN.value,
                brand=None,
                product_type=None,
                source=CategorizationSource.AI,
                confidence=0.0,
                ai_cost_usd=None
            )

    def _build_recognition_prompt(
        self,
        vendor: str,
        raw_description: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Build AI prompt for product recognition.

        Args:
            vendor: Vendor name
            raw_description: Raw product description
            context: Additional context

        Returns:
            Formatted prompt for Claude API
        """
        # Get valid categories as a list
        valid_categories = [cat.value for cat in ProductCategory]

        prompt = f"""You are a product recognition expert for a food service business in Canada.

Your task: Expand abbreviated product descriptions and categorize them precisely.

VENDOR: {vendor}
RAW DESCRIPTION: {raw_description}
"""

        # Add web lookup results if available
        if context and "web_lookup" in context:
            web_info = context["web_lookup"]
            prompt += f"\nWEB LOOKUP RESULTS (from vendor website):\n"
            if "product_name" in web_info:
                prompt += f"  Product Name: {web_info['product_name']}\n"
            if "brand" in web_info:
                prompt += f"  Brand: {web_info['brand']}\n"
            if "category_hint" in web_info:
                prompt += f"  Category Hint: {web_info['category_hint']}\n"
            prompt += "\nUSE THIS INFORMATION to improve categorization accuracy!\n"

        if context and any(k != "web_lookup" for k in context.keys()):
            # Add other context if present
            other_context = {k: v for k, v in context.items() if k != "web_lookup"}
            prompt += f"\nADDITIONAL CONTEXT: {other_context}\n"

        prompt += f"""
IMPORTANT WORKFLOW NOTES:
- Your categorization is the FIRST PASS - a human will review ambiguous items
- If the description is vague or has multiple interpretations, provide your best guess but LOWER YOUR CONFIDENCE
- Examples of ambiguous items: "EAST COAST" (seafood? coffee?), "PC PROT" (protein? protection plan?)
- Users will correct misclassifications, which improves the cache over time
- When uncertain, it's better to guess reasonably with low confidence than to mark everything as "unknown"

INSTRUCTIONS:
1. Expand abbreviations to full product name (e.g., "MTN DEW 591ML" → "Mountain Dew Citrus Soda 591mL")
2. Identify the brand if recognizable
3. Classify into ONE of these categories (choose most specific):
4. Set confidence based on certainty:
   - 0.95-0.99: Very confident (clear brand/product like "PEPSI 32 PK")
   - 0.80-0.94: Confident but some ambiguity (clear type but generic brand)
   - 0.60-0.79: Uncertain (vague description, multiple interpretations possible)
   - Below 0.60: Very uncertain (use "unknown" category instead)

FOOD CATEGORIES:
- food_hotdog: Hot dogs, sausages, wieners
- food_sandwich: Sandwiches, wraps, subs
- food_pizza: Pizza products
- food_frozen: Frozen foods, ice cream
- food_bakery: Bread, buns, pastries
- food_dairy: Cheese, yogurt, butter (not milk drinks)
- food_meat: Meat, deli products
- food_produce: Fruits, vegetables
- food_oil: Cooking oils, fats, shortening (canola, vegetable, olive oil, lard)
- food_condiment: Ketchup, mustard, mayo, sauces
- food_pantry: Canned goods, pasta, rice, spices
- food_other: Other food items

BEVERAGE CATEGORIES:
- beverage_soda: Soft drinks, cola, citrus sodas
- beverage_water: Bottled water, sparkling water
- beverage_energy: Energy drinks (Red Bull, Monster, etc.)
- beverage_sports: Sports drinks (Gatorade, Powerade, etc.)
- beverage_juice: Juice, juice boxes
- beverage_coffee: Coffee products (RTD coffee, cold brew)
- beverage_tea: Tea products (iced tea, bottled tea)
- beverage_milk: Milk-based drinks (chocolate milk, etc.)
- beverage_alcohol: Beer, wine, liquor
- beverage_other: Other beverages

SUPPLEMENT CATEGORIES:
- supplement_protein: Protein powder, protein bars
- supplement_vitamin: Vitamins, minerals
- supplement_preworkout: Pre-workout supplements
- supplement_recovery: Recovery supplements
- supplement_sports_nutrition: Sports nutrition products
- supplement_other: Other supplements

RETAIL CATEGORIES:
- retail_snack: Chips, pretzels, popcorn
- retail_candy: Candy, chocolate bars
- retail_health: Health products
- retail_accessory: Gym accessories, shaker bottles
- retail_apparel: Clothing, merchandise
- retail_other: Other retail goods

OTHER CATEGORIES:
- freight: Delivery charges, shipping fees
- packaging_container: To-go containers, cups
- packaging_bag: Bags, wrapping
- packaging_utensil: Utensils, straws
- supply_cleaning: Cleaning products
- supply_paper: Paper towels, napkins
- supply_kitchen: Kitchen supplies
- supply_other: Other supplies
- office_supply: Office supplies
- repair_equipment: Equipment repairs
- repair_building: Building repairs
- maintenance: Maintenance items
- equipment: Equipment purchases
- deposit: Bottle/can/keg deposits
- license: Licenses, permits
- unknown: Cannot determine (use only as last resort)

RESPONSE FORMAT (return ONLY this JSON, no other text):
{{
  "normalized_description": "Full product name with proper capitalization",
  "brand": "Brand name if identifiable, or null",
  "product_type": "Generic type (e.g., 'soft drink', 'energy drink')",
  "category": "exact_category_from_list_above",
  "confidence": 0.95
}}

Examples:
Input: "MTN DEW 591ML"
Output: {{"normalized_description": "Mountain Dew Citrus Soda 591mL", "brand": "Mountain Dew", "product_type": "soft drink", "category": "beverage_soda", "confidence": 0.98}}
Reasoning: Clear brand, clear product type → high confidence

Input: "SCTSBRN CFF CRM"
Output: {{"normalized_description": "Scotsburn Coffee Cream", "brand": "Scotsburn", "product_type": "cream", "category": "food_dairy", "confidence": 0.92}}
Reasoning: Recognizable abbreviation, clear product → high confidence

Input: "GATORADE COOL BLUE"
Output: {{"normalized_description": "Gatorade Cool Blue Sports Drink", "brand": "Gatorade", "product_type": "sports drink", "category": "beverage_sports", "confidence": 0.99}}
Reasoning: Well-known brand, clear product line → very high confidence

Input: "EAST COAST"
Output: {{"normalized_description": "East Coast Brand Product", "brand": "East Coast", "product_type": "unknown", "category": "unknown", "confidence": 0.55}}
Reasoning: Too vague - could be seafood, coffee, or many other products → low confidence, needs user review

Input: "EAST COAST COFFEE 1KG"
Output: {{"normalized_description": "East Coast Coffee Company Medium Roast Whole Bean Coffee 1kg", "brand": "East Coast Coffee Company", "product_type": "coffee beans", "category": "food_pantry", "confidence": 0.88}}
Reasoning: Clear product type (coffee), recognizable Canadian brand → high confidence

Input: "HOT ROD 40CT"
Output: {{"normalized_description": "Hot Rod Pepperoni Sticks 40 Count", "brand": "Hot Rod", "product_type": "meat snack", "category": "retail_snack", "confidence": 0.92}}
Reasoning: "Hot Rod" is a brand name for meat snacks, not describing hot dogs as a product → high confidence

Now classify: {raw_description}
"""

        return prompt

    def _parse_ai_response(self, response_text: str, fallback_description: str) -> RecognizedItem:
        """
        Parse JSON response from Claude API.

        Args:
            response_text: Raw response from Claude
            fallback_description: Original description (fallback if parsing fails)

        Returns:
            RecognizedItem
        """
        import json

        try:
            # Claude should return clean JSON, but extract it if wrapped in markdown
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            data = json.loads(response_text)

            return RecognizedItem(
                normalized_description=data.get("normalized_description", fallback_description),
                product_category=data.get("category", ProductCategory.UNKNOWN.value),
                brand=data.get("brand"),
                product_type=data.get("product_type"),
                source=CategorizationSource.AI,
                confidence=float(data.get("confidence", 0.5)),
                ai_cost_usd=None  # Will be set by caller
            )

        except Exception as e:
            logger.error("ai_response_parse_failed",
                        response=response_text,
                        error=str(e),
                        exc_info=True)

            # Return unknown on parse error
            return RecognizedItem(
                normalized_description=fallback_description,
                product_category=ProductCategory.UNKNOWN.value,
                brand=None,
                product_type=None,
                source=CategorizationSource.AI,
                confidence=0.0,
                ai_cost_usd=None
            )

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """
        Calculate cost of AI API call.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Total cost in USD
        """
        input_cost = (Decimal(input_tokens) / 1000) * self.input_cost_per_1k
        output_cost = (Decimal(output_tokens) / 1000) * self.output_cost_per_1k
        return input_cost + output_cost


# Singleton instance
item_recognizer = ItemRecognizer()
