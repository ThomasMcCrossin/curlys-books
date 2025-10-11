#!/usr/bin/env python3
"""
Test web lookup feature with Costco items

Tests the experimental web lookup feature that searches vendor websites
to verify product details before categorization.

Usage:
    docker compose exec api python scripts/test_web_lookup.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from decimal import Decimal

from packages.common.database import sessionmanager
from packages.common.config import get_settings
from packages.domain.categorization.categorization_service import categorization_service

logger = structlog.get_logger()


# Test a few challenging Costco items
TEST_ITEMS = [
    ("54491", "HOT ROD 40CT", Decimal("18.49")),
    ("252886", "EAST COAST", Decimal("231.92")),
    ("310062", "PEPSI 32 PK", Decimal("83.15")),
    ("1868765", "ALANI C&C", Decimal("142.84")),
]


async def main():
    """Test web lookup with Costco items"""
    settings = get_settings()

    print("=" * 80)
    print("WEB LOOKUP TEST - Costco")
    print("=" * 80)
    print(f"Web lookup enabled: {settings.categorization_web_lookup_enabled}")
    print(f"Lookup timeout: {settings.categorization_web_lookup_timeout}s")
    print()

    if not settings.categorization_web_lookup_enabled:
        print("⚠ Web lookup is DISABLED. Set CATEGORIZATION_WEB_LOOKUP_ENABLED=true in .env")
        return

    sessionmanager.init(settings.database_url)

    async with sessionmanager.session() as db:
        for i, (sku, description, amount) in enumerate(TEST_ITEMS, 1):
            print(f"\n{'='*80}")
            print(f"Test {i}/{len(TEST_ITEMS)}: {description}")
            print(f"SKU: {sku}, Amount: ${amount}")
            print(f"{'='*80}")

            # Categorize (will attempt web lookup)
            result = await categorization_service.categorize_line_item(
                vendor="Costco",
                sku=sku,
                raw_description=description,
                line_total=amount,
                db=db
            )

            print(f"\nRESULTS:")
            print(f"  Normalized: {result.normalized_description}")
            print(f"  Category: {result.product_category}")
            print(f"  Account: {result.account_code} - {result.account_name}")
            print(f"  Confidence: {result.confidence:.2%}")
            print(f"  Source: {result.source.value}")

            if result.requires_review:
                print(f"  ⚠ REVIEW REQUIRED")
            else:
                print(f"  ✓ Auto-approved")

            if result.ai_cost_usd:
                print(f"  Cost: ${float(result.ai_cost_usd):.6f}")

            # Small delay to avoid rate limiting
            await asyncio.sleep(1)

    await sessionmanager.close()

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)
    print("\nCheck logs above for:")
    print("  [info] product_lookup_started - Web lookup initiated")
    print("  [info] product_lookup_success - Product found on website")
    print("  [info] web_lookup_found - Product details extracted")
    print("  [warning] product_lookup_timeout - Vendor website timeout")
    print("  [warning] product_lookup_failed - HTTP error or blocked")


if __name__ == "__main__":
    asyncio.run(main())
