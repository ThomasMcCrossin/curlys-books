#!/usr/bin/env python3
"""
Test script for OCR provider refactor with Walmart receipt.

Tests:
1. New OCR provider architecture
2. Full receipt processing pipeline
3. Product categorization with fresh cache
"""
import asyncio
import sys
from pathlib import Path
from decimal import Decimal

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.parsers.ocr import extract_text_from_receipt
from packages.parsers.vendor_dispatcher import parse_receipt
from packages.common.schemas.receipt_normalized import EntityType
from packages.domain.categorization.categorization_service import categorization_service
from packages.common.database import get_db_session
import structlog

logger = structlog.get_logger()


async def test_walmart_receipt():
    """Test complete pipeline with Walmart receipt"""

    # Use the existing Walmart receipt
    receipt_path = "/srv/curlys-books/objects/corp/acafec2a-00e1-4484-96e7-ccb05e43185f/original.heic"

    print("=" * 80)
    print("TESTING OCR PROVIDER REFACTOR - WALMART RECEIPT")
    print("=" * 80)
    print()

    # STEP 1: OCR Extraction
    print("STEP 1: OCR Extraction (new provider architecture)")
    print("-" * 80)

    ocr_result = await extract_text_from_receipt(receipt_path)

    print(f"✅ OCR Method: {ocr_result.method}")
    print(f"✅ Confidence: {ocr_result.confidence:.2%}")
    print(f"✅ Pages: {ocr_result.page_count}")
    print(f"✅ Text length: {len(ocr_result.text)} chars")
    print(f"✅ Bounding boxes: {len(ocr_result.bounding_boxes)}")
    print()

    # Show first few lines
    lines = ocr_result.text.split('\n')[:10]
    print("First 10 lines:")
    for i, line in enumerate(lines, 1):
        print(f"  {i:2d}. {line}")
    print()

    # STEP 2: Vendor Parsing
    print("STEP 2: Vendor Parsing")
    print("-" * 80)

    parsed_receipt = parse_receipt(ocr_result.text, entity=EntityType.CORP)

    print(f"✅ Vendor: {parsed_receipt.vendor_guess}")
    print(f"✅ Date: {parsed_receipt.purchase_date}")
    print(f"✅ Subtotal: ${parsed_receipt.subtotal}")
    print(f"✅ Tax: ${parsed_receipt.tax_total}")
    print(f"✅ Total: ${parsed_receipt.total}")
    print(f"✅ Line items: {len(parsed_receipt.lines)}")
    print()

    # Show a few line items
    print("Sample line items:")
    for i, line in enumerate(parsed_receipt.lines[:5], 1):
        desc = line.item_description or "N/A"
        print(f"  {i}. {desc[:40]:40s} ${line.line_total}")
    print()

    # STEP 3: AI Categorization (with fresh cache)
    print("STEP 3: AI Categorization (cache was cleared)")
    print("-" * 80)

    categorized_count = 0
    cached_count = 0
    ai_count = 0
    total_cost = Decimal("0")

    async for session in get_db_session():
        try:
            for i, line in enumerate(parsed_receipt.lines, 1):
                if not line.sku and not line.item_description:
                    continue

                desc = line.item_description or "N/A"
                print(f"\n[{i}/{len(parsed_receipt.lines)}] {desc[:50]}")
                print(f"  SKU: {line.sku or 'N/A'}")

                try:
                    result = await categorization_service.categorize_line_item(
                        vendor="Walmart",
                        sku=line.sku,
                        raw_description=line.item_description,
                        line_total=line.line_total or Decimal("0"),
                        db=session
                    )

                    categorized_count += 1

                    if result.source == "cached":
                        cached_count += 1
                        print(f"  ✅ Category: {result.product_category} (CACHED)")
                    else:
                        ai_count += 1
                        print(f"  🤖 Category: {result.product_category} (AI - ${result.ai_cost_usd:.4f})")

                    print(f"  Account: {result.account_code} - {result.account_name}")
                    print(f"  Confidence: {result.confidence:.0%}")

                    if result.requires_review:
                        print(f"  ⚠️  REQUIRES REVIEW")

                    if result.ai_cost_usd:
                        total_cost += result.ai_cost_usd

                except Exception as e:
                    print(f"  ❌ Categorization failed: {e}")

            await session.commit()
            break

        except Exception as e:
            print(f"\n❌ Database error: {e}")
            await session.rollback()
            break

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"OCR Method: {ocr_result.method}")
    print(f"OCR Confidence: {ocr_result.confidence:.2%}")
    print(f"Vendor: {parsed_receipt.vendor_guess}")
    print(f"Total: ${parsed_receipt.total}")
    print(f"Line Items: {len(parsed_receipt.lines)}")
    print(f"Categorized: {categorized_count}")
    print(f"  - From Cache: {cached_count}")
    print(f"  - From AI: {ai_count}")
    print(f"Total AI Cost: ${total_cost:.4f}")
    print("=" * 80)
    print()

    # Test result
    if ocr_result.method == "textract" and ocr_result.confidence > 0.95:
        print("✅ OCR PROVIDER REFACTOR TEST PASSED!")
    else:
        print("⚠️  OCR test did not use expected provider")

    if categorized_count > 0:
        print("✅ CATEGORIZATION TEST PASSED!")
    else:
        print("❌ CATEGORIZATION FAILED")


if __name__ == "__main__":
    asyncio.run(test_walmart_receipt())
