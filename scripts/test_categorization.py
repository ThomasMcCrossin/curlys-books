#!/usr/bin/env python3
"""
Test script for AI categorization system

Tests the two-stage categorization:
1. Stage 1 (AI): Item recognition with caching
2. Stage 2 (Rules): Account mapping

Usage:
    docker compose exec api python scripts/test_categorization.py
"""
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from packages.common.config import get_settings
from packages.common.database import sessionmanager
from packages.domain.categorization.categorization_service import categorization_service

logger = structlog.get_logger()


async def main():
    """Test categorization with sample line items."""
    settings = get_settings()

    # Initialize database session manager
    sessionmanager.init(settings.database_url)

    # Test cases covering different product categories
    test_items = [
        {
            "vendor": "GFS Canada",
            "sku": "1234567",
            "raw_description": "MTN DEW 591ML",
            "line_total": Decimal("24.99"),
            "expected_category": "beverage_soda",
            "expected_account": "5011",
        },
        {
            "vendor": "GFS Canada",
            "sku": "7654321",
            "raw_description": "GATORADE COOL BLUE",
            "line_total": Decimal("18.50"),
            "expected_category": "beverage_sports",
            "expected_account": "5014",
        },
        {
            "vendor": "Costco",
            "sku": "987654",
            "raw_description": "KIRKLAND PROTEIN BAR",
            "line_total": Decimal("29.99"),
            "expected_category": "supplement_protein",
            "expected_account": "5021",
        },
        {
            "vendor": "GFS Canada",
            "sku": "111222",
            "raw_description": "HOT DOG BUNS 8PK",
            "line_total": Decimal("3.99"),
            "expected_category": "food_bakery",
            "expected_account": "5005",
        },
        {
            "vendor": "GFS Canada",
            "sku": "333444",
            "raw_description": "TO-GO CUPS 16OZ 50CT",
            "line_total": Decimal("12.99"),
            "expected_category": "packaging_container",
            "expected_account": "5201",
        },
        {
            "vendor": "Home Depot",
            "sku": None,  # No SKU - will always call AI
            "raw_description": "COMMERCIAL MIXER",
            "line_total": Decimal("3500.00"),  # Over capitalization threshold
            "expected_category": "equipment",
            "expected_account": "1500",  # Fixed asset
        },
        {
            "vendor": "Home Depot",
            "sku": None,
            "raw_description": "CLEANING SUPPLIES",
            "line_total": Decimal("45.00"),
            "expected_category": "supply_cleaning",
            "expected_account": "5204",
        },
    ]

    print("=" * 80)
    print("AI CATEGORIZATION SYSTEM TEST")
    print("=" * 80)
    print()

    async with sessionmanager.session() as db:
        total_cost = Decimal("0")
        cache_hits = 0
        ai_calls = 0

        for i, item in enumerate(test_items, 1):
            print(f"Test {i}/{len(test_items)}: {item['vendor']} - {item['raw_description']}")
            print("-" * 80)

            try:
                result = await categorization_service.categorize_line_item(
                    vendor=item["vendor"],
                    raw_description=item["raw_description"],
                    line_total=item["line_total"],
                    db=db,
                    sku=item["sku"],
                )

                # Track stats
                if result.source.value == "cache":
                    cache_hits += 1
                    print("✓ Cache hit (FREE!)")
                elif result.source.value == "ai":
                    ai_calls += 1
                    if result.ai_cost_usd:
                        total_cost += result.ai_cost_usd
                        print(f"✓ AI call (cost: ${float(result.ai_cost_usd):.6f})")

                # Display results
                print(f"  Raw: {result.raw_description}")
                print(f"  Normalized: {result.normalized_description}")
                print(f"  Brand: {result.brand or 'N/A'}")
                print(f"  Category: {result.product_category}")
                print(f"  Account: {result.account_code} - {result.account_name}")
                print(f"  Confidence: {result.confidence:.2%}")
                print(f"  Requires Review: {result.requires_review}")

                # Validate expectations
                if item.get("expected_category"):
                    if result.product_category == item["expected_category"]:
                        print(f"  ✓ Category matches expected: {item['expected_category']}")
                    else:
                        print(f"  ✗ Category mismatch! Expected: {item['expected_category']}, Got: {result.product_category}")

                if item.get("expected_account"):
                    if result.account_code == item["expected_account"]:
                        print(f"  ✓ Account matches expected: {item['expected_account']}")
                    else:
                        print(f"  ✗ Account mismatch! Expected: {item['expected_account']}, Got: {result.account_code}")

                print()

            except Exception as e:
                print(f"  ✗ ERROR: {str(e)}")
                logger.error("categorization_test_failed",
                           vendor=item["vendor"],
                           description=item["raw_description"],
                           error=str(e),
                           exc_info=True)
                print()
                continue

        # Summary
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total items tested: {len(test_items)}")
        print(f"Cache hits: {cache_hits} (FREE)")
        print(f"AI calls: {ai_calls} (${float(total_cost):.6f})")
        print(f"Average cost per item: ${float(total_cost / len(test_items)):.6f}")
        print()

        # Run again to test caching
        if ai_calls > 0:
            print("=" * 80)
            print("CACHE TEST - Running same items again...")
            print("=" * 80)
            print()

            second_run_cost = Decimal("0")
            second_cache_hits = 0

            for item in test_items:
                if item["sku"]:  # Only items with SKUs can be cached
                    result = await categorization_service.categorize_line_item(
                        vendor=item["vendor"],
                        raw_description=item["raw_description"],
                        line_total=item["line_total"],
                        db=db,
                        sku=item["sku"],
                    )

                    if result.source.value == "cache":
                        second_cache_hits += 1

                    if result.ai_cost_usd:
                        second_run_cost += result.ai_cost_usd

            items_with_sku = sum(1 for item in test_items if item["sku"])
            cache_rate = (second_cache_hits / items_with_sku * 100) if items_with_sku > 0 else 0

            print(f"Second run cache hits: {second_cache_hits}/{items_with_sku} ({cache_rate:.1f}%)")
            print(f"Second run cost: ${float(second_run_cost):.6f}")
            print()

            if cache_rate == 100:
                print("✓ All items with SKUs were cached successfully!")
            else:
                print("✗ Some items were not cached (expected for items without SKUs)")

    await sessionmanager.close()


if __name__ == "__main__":
    asyncio.run(main())
