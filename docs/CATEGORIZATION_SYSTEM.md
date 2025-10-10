# AI Categorization System

**Phase 1.5** - Two-stage AI categorization for receipt line items

## Overview

Automatically categorizes receipt line items into granular GL accounts using:
1. **Stage 1 (AI)**: Claude API expands vendor abbreviations and classifies products
2. **Stage 2 (Rules)**: Deterministic mapping from categories to GL accounts

## Cost Optimization

### Caching Strategy
- **First time** seeing vendor+SKU: AI call (~$0.001-0.003 per item)
- **Subsequent times**: Cache hit from `shared.product_mappings` (FREE)
- **After 6 months**: Expected 95%+ cache hit rate, <$1/month AI costs

### Example Flow
```
1st GFS receipt with Mountain Dew 591mL:
  Input: vendor="GFS Canada", sku="1234567", desc="MTN DEW 591ML"
  → AI Call ($0.002)
  → Output: "Mountain Dew Citrus Soda 591mL" → category: beverage_soda
  → Account: 5011 (COGS - Beverage - Soda)
  → Cache: Store vendor+SKU → category mapping

2nd+ receipts with same SKU:
  Input: vendor="GFS Canada", sku="1234567", desc="MTN DEW 591ML"
  → Cache Hit (FREE)
  → Output: Same categorization, no AI call
```

## Architecture

### Stage 1: AI Recognition (`item_recognizer.py`)

**Purpose**: Expand vendor abbreviations and classify products

**Model**: Anthropic Claude (claude-3-5-sonnet-20241022)

**Pricing**:
- Input: $0.003 per 1K tokens
- Output: $0.015 per 1K tokens
- Typical item: ~$0.001-0.003 per classification

**Process**:
1. Check cache: `shared.product_mappings` by vendor+SKU
2. If cache miss → Call Claude API with detailed prompt
3. Parse JSON response with normalized description + category
4. Cache result for future use

**Output**: `RecognizedItem`
- `normalized_description`: "Mountain Dew Citrus Soda 591mL"
- `product_category`: "beverage_soda"
- `brand`: "Mountain Dew"
- `confidence`: 0.95
- `source`: "cache" or "ai"
- `ai_cost_usd`: Decimal or None

### Stage 2: Account Mapping (`account_mapper.py`)

**Purpose**: Map product categories to GL account codes

**Model**: 100% rule-based (no AI, no cost)

**Process**:
1. Lookup category in `CATEGORY_MAP` dictionary
2. Apply special rules (e.g., equipment capitalization)
3. Return account code + metadata

**Output**: `AccountMapping`
- `account_code`: "5011"
- `account_name`: "COGS - Beverage - Soda"
- `confidence`: 1.0
- `requires_review`: false
- `mapping_rule`: "beverage_soda → 5011"

### Orchestrator (`categorization_service.py`)

**Purpose**: Combine both stages and provide high-level API

**Methods**:

#### `categorize_line_item()`
Categorize a single receipt line item.

```python
result = await categorization_service.categorize_line_item(
    vendor="GFS Canada",
    sku="1234567",
    raw_description="MTN DEW 591ML",
    line_total=Decimal("24.99"),
    db=db_session
)

# Result: CategorizedLineItem
# - Complete categorization (Stage 1 + Stage 2)
# - Overall confidence (min of both stages)
# - Requires review flag
# - Cost tracking
```

#### `categorize_receipt_lines()`
Batch process multiple line items with context awareness.

```python
results = await categorization_service.categorize_receipt_lines(
    vendor="GFS Canada",
    line_items=[
        {"raw_description": "MTN DEW 591ML", "line_total": Decimal("24.99"), "sku": "1234567"},
        {"raw_description": "GATORADE COOL BLUE", "line_total": Decimal("18.50"), "sku": "7654321"},
        # ... more items
    ],
    db=db_session
)

# Returns: list[CategorizedLineItem]
# Logs: Cache hit rate, AI call count, total cost
```

## Product Categories

### Food (5000-5009)
- `food_hotdog` → 5001 (COGS - Food - Hot Dogs)
- `food_sandwich` → 5002 (COGS - Food - Sandwiches)
- `food_pizza` → 5003 (COGS - Food - Pizza)
- `food_frozen` → 5004 (COGS - Food - Frozen)
- `food_bakery` → 5005 (COGS - Food - Bakery)
- `food_dairy` → 5006 (COGS - Food - Dairy)
- `food_meat` → 5007 (COGS - Food - Meat/Deli)
- `food_produce` → 5008 (COGS - Food - Produce)
- `food_condiment`, `food_pantry`, `food_other` → 5009 (COGS - Food - Other)

### Beverage (5010-5019)
- `beverage_soda` → 5011 (COGS - Beverage - Soda)
- `beverage_water` → 5012 (COGS - Beverage - Water)
- `beverage_energy` → 5013 (COGS - Beverage - Energy Drinks)
- `beverage_sports` → 5014 (COGS - Beverage - Sports Drinks)
- `beverage_juice` → 5015 (COGS - Beverage - Juice)
- `beverage_coffee`, `beverage_tea` → 5016 (COGS - Beverage - Coffee/Tea)
- `beverage_milk` → 5017 (COGS - Beverage - Milk Products)
- `beverage_alcohol` → 5018 (COGS - Beverage - Alcohol)
- `beverage_other` → 5019 (COGS - Beverage - Other)

### Supplements (5020-5029)
- `supplement_protein` → 5021 (COGS - Supplements - Protein)
- `supplement_vitamin` → 5022 (COGS - Supplements - Vitamins)
- `supplement_preworkout` → 5023 (COGS - Supplements - Pre-Workout)
- `supplement_recovery` → 5024 (COGS - Supplements - Recovery)
- `supplement_sports_nutrition` → 5025 (COGS - Supplements - Sports Nutrition)
- `supplement_other` → 5029 (COGS - Supplements - Other)

### Retail Goods (5030-5039)
- `retail_snack` → 5031 (COGS - Retail - Snacks/Chips)
- `retail_candy` → 5032 (COGS - Retail - Candy/Chocolate)
- `retail_health` → 5033 (COGS - Retail - Health Products)
- `retail_accessory` → 5034 (COGS - Retail - Accessories)
- `retail_apparel` → 5035 (COGS - Retail - Apparel)
- `retail_other` → 5039 (COGS - Retail - Other)

### Other Categories
- `freight` → 5100 (Freight In)
- `packaging_container` → 5201 (Packaging - Containers/Cups)
- `packaging_bag` → 5202 (Packaging - Bags/Wrapping)
- `packaging_utensil` → 5203 (Packaging - Utensils/Straws)
- `supply_cleaning` → 5204 (Supplies - Cleaning)
- `supply_paper` → 5205 (Supplies - Paper Products)
- `supply_kitchen` → 5206 (Supplies - Kitchen)
- `supply_other` → 5209 (Supplies - Other)
- `office_supply` → 6600 (Office Supplies)
- `repair_equipment`, `repair_building`, `maintenance` → 6300 (Repairs & Maintenance)
- `equipment` → 1500 (if ≥$2500) or 6300 (if <$2500)
- `deposit` → 9000 (Deposits - Bottle/Container)
- `license` → 6800 (Licenses & Permits)
- `unknown` → 9100 (Pending Receipt - No ITC) ⚠️ Requires review

## Special Business Rules

### Equipment Capitalization
```python
CAPITALIZATION_THRESHOLD = Decimal("2500.00")

If product_category == "equipment":
    if line_total >= $2500 → Account 1500 (Fixed Asset)
    if line_total < $2500  → Account 6300 (Expense)
```

### Review Requirements
Items flagged for manual review when:
- Overall confidence < 0.8
- Category = "unknown"
- Equipment being capitalized (≥$2500)

## Chart of Accounts

### Parent/Child Structure
Granular sub-accounts roll up to parent accounts for tax reporting:

```
5000 (COGS - Food) ← Parent for GIFI/T2125
  ├── 5001 (Hot Dogs)
  ├── 5002 (Sandwiches)
  ├── 5003 (Pizza)
  └── ... (all food sub-accounts)

5010 (COGS - Beverage) ← Parent for GIFI/T2125
  ├── 5011 (Soda)
  ├── 5012 (Water)
  ├── 5013 (Energy Drinks)
  └── ... (all beverage sub-accounts)
```

**Tax Compliance**: Sub-accounts inherit parent's GIFI code and T2125 line for tax reporting.

**Analytics**: P&L can show either:
- Detailed view (all sub-accounts)
- Tax view (rolled up to parents)

## Usage

### Basic Usage

```python
from packages.domain.categorization.categorization_service import categorization_service
from packages.common.database import get_db_session
from decimal import Decimal

async with get_db_session() as db:
    result = await categorization_service.categorize_line_item(
        vendor="GFS Canada",
        sku="1234567",
        raw_description="MTN DEW 591ML",
        line_total=Decimal("24.99"),
        db=db
    )

    print(f"Account: {result.account_code} - {result.account_name}")
    print(f"Category: {result.product_category}")
    print(f"Confidence: {result.confidence:.2%}")
    print(f"Cost: ${result.ai_cost_usd or 0}")
```

### Batch Processing

```python
from packages.domain.categorization.categorization_service import categorization_service

results = await categorization_service.categorize_receipt_lines(
    vendor="GFS Canada",
    line_items=receipt_lines,  # List of dicts with raw_description, line_total, sku
    db=db
)

# Access results
for result in results:
    if result.requires_review:
        # Send to review queue
        pass
    else:
        # Auto-post to journal
        pass
```

## Testing

### Test Script

Run comprehensive test with 7 sample items covering all major categories:

```bash
docker compose exec api python scripts/test_categorization.py
```

**Test Coverage**:
- Beverage (soda, sports drinks)
- Supplements (protein)
- Food (bakery)
- Packaging (containers)
- Equipment (capitalization threshold)
- Supplies (cleaning)
- Cache hit rate validation (second run)

**Output**:
- Per-item categorization results
- Category and account validation
- Cache hit statistics
- Total cost tracking
- Cache effectiveness test

### Manual Testing

```python
# Start Python shell in API container
docker compose exec api python

from packages.domain.categorization.categorization_service import categorization_service
from packages.common.database import get_db_session
from decimal import Decimal
import asyncio

async def test():
    async with get_db_session() as db:
        result = await categorization_service.categorize_line_item(
            vendor="Your Vendor",
            sku="12345",
            raw_description="Your Description",
            line_total=Decimal("19.99"),
            db=db
        )
        print(result.model_dump_json(indent=2))

asyncio.run(test())
```

## Integration Points

### Receipt Processing Pipeline

1. **Upload** → Receipt saved with raw OCR text
2. **Parsing** → Vendor-specific parser extracts line items
3. **Categorization** ← YOU ARE HERE
   - Call `categorization_service.categorize_receipt_lines()`
   - Store results in `receipt_line_items` table
4. **Review** → If `requires_review=True`, send to review queue
5. **Posting** → Create journal entries with account codes

### Database Schema

#### Input (from receipt parsers)
```sql
receipt_line_items:
  - vendor_canonical (text)
  - sku (text, nullable)
  - description_raw (text)
  - line_total (numeric)
```

#### Output (from categorization)
```sql
receipt_line_items:
  - description_normalized (text)
  - product_category (text)
  - brand (text, nullable)
  - account_code (text)
  - confidence (numeric)
  - requires_review (boolean)
  - ai_cost_usd (numeric, nullable)
```

#### Cache Table
```sql
shared.product_mappings:
  - vendor_canonical (text)
  - sku (text)
  - description_normalized (text)
  - product_category (text)
  - account_code (text)
  - times_seen (integer)
  - user_confidence (numeric)
```

## Configuration

### Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-api03-...

# Optional
CAPITALIZATION_THRESHOLD=2500  # Equipment threshold (default: $2500)
```

### Logging

All categorization events are logged with `structlog`:

```python
logger.info("categorization_started", vendor="GFS", sku="1234567")
logger.info("cache_hit", category="beverage_soda", times_seen=15)
logger.info("cache_miss", message="Calling AI for recognition")
logger.info("ai_recognition_complete", cost_usd=0.0023)
logger.info("categorization_complete", account="5011", confidence=0.95)
```

## Performance

### Expected Performance (after 6 months)

**Assumptions**:
- 1000 receipts/month
- 10 line items/receipt average
- 10,000 line items/month
- 60% unique vendor+SKU combinations

**First Month**:
- AI calls: ~6000 (60% unique)
- Cost: ~$12-18
- Cache hit rate: 0%

**Month 6**:
- AI calls: ~500 (5% new SKUs)
- Cost: ~$1-2
- Cache hit rate: 95%

**Year 1+**:
- AI calls: ~100-200/month (2% new SKUs)
- Cost: <$1/month
- Cache hit rate: 98%+

## Known Limitations

1. **SKU Required for Caching**: Items without vendor SKUs cannot be cached (AI call every time)
2. **Vendor Name Normalization**: Must use canonical vendor name for cache hits
3. **Model Context**: Claude prompt includes all 40+ categories (~2000 tokens input cost)
4. **Equipment Review**: All capitalized equipment (≥$2500) requires manual review
5. **Unknown Category**: Falls back to account 9100 (Pending Receipt) with review flag

## Future Enhancements

- [ ] Add vendor name normalization/aliases
- [ ] Implement confidence-based learning (update cache when users correct)
- [ ] Add batch API support for parallel processing
- [ ] Create admin UI for cache management
- [ ] Export category statistics for P&L analytics
- [ ] Add category-level sales reporting
- [ ] Implement multi-model fallback (GPT-4 if Claude fails)

## Files

- `packages/domain/categorization/categorization_service.py` - Main orchestrator
- `packages/domain/categorization/item_recognizer.py` - AI recognition (Stage 1)
- `packages/domain/categorization/account_mapper.py` - Rule-based mapping (Stage 2)
- `packages/domain/categorization/schemas.py` - Pydantic data models
- `infra/db/seeds/chart_of_accounts.csv` - Expanded chart with sub-accounts
- `scripts/test_categorization.py` - Comprehensive test script
- `docs/CATEGORIZATION_SYSTEM.md` - This file

## Support

For questions or issues:
1. Check logs: `docker compose logs api | grep categorization`
2. Run test script: `docker compose exec api python scripts/test_categorization.py`
3. Review cache table: `SELECT * FROM shared.product_mappings LIMIT 10;`
4. Check AI costs: Sum of `ai_cost_usd` in `receipt_line_items` table
