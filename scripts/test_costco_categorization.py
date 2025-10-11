#!/usr/bin/env python3
"""
Stress test: Costco receipt with extremely abbreviated item names

Costco is known for very short, cryptic item descriptions:
- "ALANI C&C" (energy drink)
- "NESTLE 24CT" (water? chocolate? coffee?)
- "KETCHP 2.84L" (ketchup)
- "HB ORIG TAPE" (Hubbard tape?)
- "POUTINE CURD" (cheese curds)

This tests the AI's ability to expand abbreviations with minimal context.

Usage:
    docker compose exec api python scripts/test_costco_categorization.py
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


# Sample of challenging Costco items from the receipt
COSTCO_TEST_ITEMS = [
    # (SKU, Description, Amount, Expected Category Guess)
    ("54491", "HOT ROD 40CT", Decimal("18.49"), "retail_snack or retail_candy"),
    ("1868765", "ALANI C&C", Decimal("142.84"), "beverage_energy"),
    ("1897026", "YARDBAGS", Decimal("17.99"), "packaging_bag or supply_other"),
    ("252886", "EAST COAST", Decimal("231.92"), "food_meat or food_frozen?"),
    ("369437", "3 YR PC PROT", Decimal("99.99"), "equipment or office_supply"),
    ("1829553", "SMART PLUG", Decimal("19.99"), "retail_accessory or equipment"),
    ("1178208", "KETCHP 2.84L", Decimal("159.84"), "food_condiment"),
    ("3339797", "NESTLE 24CT", Decimal("131.94"), "beverage_water? food_frozen?"),
    ("2768073", "GUMMY WORMS", Decimal("47.97"), "retail_candy"),
    ("50125", "ALCAN FOIL", Decimal("31.89"), "packaging_container or supply_kitchen"),
    ("310062", "PEPSI 32 PK", Decimal("83.15"), "beverage_soda"),
    ("969786", "PANDA COOKIE", Decimal("14.99"), "retail_snack or retail_candy"),
    ("1943316", "ALANI", Decimal("121.40"), "beverage_energy"),
    ("14861", "AIRHEADS", Decimal("23.67"), "retail_candy"),
    ("4284466", "BEARPAWS", Decimal("11.99"), "retail_snack or retail_candy"),
    ("106010", "HB ORIG TAPE", Decimal("239.88"), "supply_other or packaging_?"),
    ("324143", "PURE PROTEIN", Decimal("49.98"), "supplement_protein"),
    ("239248", "MARS 18CT", Decimal("287.82"), "retail_candy"),
    ("4308266", "CADBURY 24CT", Decimal("175.92"), "retail_candy"),
    ("1814466", "POUTINE CURD", Decimal("389.70"), "food_dairy"),
    ("237785", "MOZZA STICKS", Decimal("543.68"), "food_dairy"),
    ("1323118", "KS PARCHMENT", Decimal("19.99"), "packaging_container or supply_kitchen"),
    ("308636", "CRUSH 32 PK", Decimal("33.26"), "beverage_soda"),
    ("1009603", "NERDS GUMMY", Decimal("155.94"), "retail_candy"),
]


async def main():
    """Test Costco receipt categorization"""
    settings = get_settings()
    sessionmanager.init(settings.database_url)

    print("=" * 80)
    print("COSTCO STRESS TEST: Abbreviated Item Names")
    print("=" * 80)
    print(f"Items to categorize: {len(COSTCO_TEST_ITEMS)}")
    print()
    print("Costco uses extremely short item descriptions with minimal context.")
    print("This tests the AI's ability to expand abbreviations and infer categories.")
    print()

    async with sessionmanager.session() as db:
        total_cost = Decimal("0")
        cache_hits = 0
        ai_calls = 0
        results = []

        for i, (sku, description, amount, expected) in enumerate(COSTCO_TEST_ITEMS, 1):
            print(f"\n[{i}/{len(COSTCO_TEST_ITEMS)}] {description}")
            print(f"  SKU: {sku}")
            print(f"  Amount: ${amount}")
            print(f"  Expected: {expected}")

            # Categorize
            result = await categorization_service.categorize_line_item(
                vendor="Costco",
                sku=sku,
                raw_description=description,
                line_total=amount,
                db=db
            )

            # Track stats
            if result.source.value == "cache":
                cache_hits += 1
                print(f"  ✓ Cache hit (FREE)")
            else:
                ai_calls += 1
                if result.ai_cost_usd:
                    total_cost += result.ai_cost_usd
                    print(f"  ✓ AI call (${float(result.ai_cost_usd):.6f})")

            print(f"  → Normalized: {result.normalized_description}")
            print(f"  → Category: {result.product_category}")
            print(f"  → Account: {result.account_code} - {result.account_name}")
            print(f"  → Confidence: {result.confidence:.2%}")

            if result.requires_review:
                print(f"  ⚠ Review needed")

            results.append({
                "sku": sku,
                "raw": description,
                "normalized": result.normalized_description,
                "category": result.product_category,
                "account": result.account_code,
                "confidence": result.confidence,
                "review": result.requires_review,
            })

        print()
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Items categorized: {len(COSTCO_TEST_ITEMS)}")
        print(f"Cache hits: {cache_hits}")
        print(f"AI calls: {ai_calls}")
        print(f"Total AI cost: ${float(total_cost):.6f}")
        print(f"Average cost per item: ${float(total_cost / len(COSTCO_TEST_ITEMS)):.6f}")
        print()

        # Analyze results
        needs_review = sum(1 for r in results if r["review"])
        avg_confidence = sum(r["confidence"] for r in results) / len(results)

        print("ANALYSIS")
        print("-" * 80)
        print(f"Items requiring review: {needs_review} ({needs_review/len(results):.1%})")
        print(f"Average confidence: {avg_confidence:.2%}")
        print()

        # Show low confidence items
        low_confidence = [r for r in results if r["confidence"] < 0.7]
        if low_confidence:
            print("LOW CONFIDENCE ITEMS (< 70%):")
            for r in low_confidence:
                print(f"  • {r['raw']} → {r['normalized']}")
                print(f"    Category: {r['category']}, Confidence: {r['confidence']:.2%}")
        else:
            print("✓ All items categorized with ≥70% confidence")

        print()
        print("=" * 80)
        print("COSTCO-SPECIFIC CHALLENGES IDENTIFIED:")
        print("=" * 80)

        # Identify patterns in the results
        beverage_items = [r for r in results if r["category"].startswith("beverage_")]
        candy_items = [r for r in results if r["category"] == "retail_candy"]
        dairy_items = [r for r in results if r["category"] == "food_dairy"]

        print(f"✓ Beverages: {len(beverage_items)} (Alani, Pepsi, Crush)")
        print(f"✓ Candy/Snacks: {len(candy_items)} (Airheads, Mars, Nerds, etc.)")
        print(f"✓ Dairy: {len(dairy_items)} (Poutine curds, mozzarella)")
        print()
        print("KEY FINDINGS:")
        print("- Costco uses brand names + pack counts (e.g., 'MARS 18CT', 'PEPSI 32 PK')")
        print("- Heavy abbreviation (KETCHP, MOZZA, POUTINE CURD)")
        print("- Brand recognition critical (ALANI = energy drink, not a food brand)")
        print("- Multi-use items unclear without context (HB ORIG TAPE, 3 YR PC PROT)")

    await sessionmanager.close()


if __name__ == "__main__":
    asyncio.run(main())
