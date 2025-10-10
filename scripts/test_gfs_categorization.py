#!/usr/bin/env python3
"""
Test GFS receipt parsing and categorization with real receipt

Usage:
    docker compose exec api python scripts/test_gfs_categorization.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from decimal import Decimal

from packages.parsers.ocr_engine import extract_text_from_receipt
from packages.parsers.vendors.gfs_parser import GFSParser
from packages.common.database import sessionmanager
from packages.common.config import get_settings
from packages.domain.categorization.categorization_service import categorization_service
from packages.common.schemas.receipt_normalized import EntityType

logger = structlog.get_logger()


async def main():
    """Test GFS receipt parsing and categorization"""
    settings = get_settings()
    sessionmanager.init(settings.database_url)

    # Test with real GFS receipt
    gfs_receipt_path = "vendor-samples/CurlysCanteenCorp/GFS/Copy of 9002081541.pdf"

    print("=" * 80)
    print("GFS RECEIPT PARSING & CATEGORIZATION TEST")
    print("=" * 80)
    print(f"File: {gfs_receipt_path}")
    print()

    # Step 1: Extract text (should use direct PDF extraction, not OCR)
    print("Step 1: Extracting text from PDF...")
    ocr_result = await extract_text_from_receipt(gfs_receipt_path)

    print(f"✓ Method: {ocr_result.method}")
    print(f"✓ Confidence: {ocr_result.confidence:.2%}")
    print(f"✓ Pages: {ocr_result.page_count}")
    print(f"✓ Text length: {len(ocr_result.text)} characters")

    if ocr_result.method == "pdf_text_extraction":
        print("✓ Used direct PDF text extraction (fast, no OCR needed!)")
    else:
        print("⚠ Used OCR (slower, might indicate scanned PDF)")
    print()

    # Step 2: Parse with GFS parser
    print("Step 2: Parsing with GFS parser...")
    parser = GFSParser()
    receipt = parser.parse(ocr_result.text, entity=EntityType.CORP)

    print(f"✓ Vendor: {receipt.vendor_guess}")
    print(f"✓ Invoice: {receipt.invoice_number}")
    print(f"✓ Date: {receipt.purchase_date}")
    print(f"✓ Subtotal: ${receipt.subtotal}")
    print(f"✓ Tax: ${receipt.tax_total}")
    print(f"✓ Total: ${receipt.total}")
    print(f"✓ Line items: {len(receipt.lines)}")
    print()

    # Step 3: Categorize first 5 line items
    print("Step 3: Categorizing line items with AI...")
    print("-" * 80)

    async with sessionmanager.session() as db:
        total_cost = Decimal("0")
        cache_hits = 0
        ai_calls = 0

        for i, line in enumerate(receipt.lines[:5], 1):
            # Extract SKU and description from the line
            sku = line.vendor_sku
            description = line.item_description
            line_total = line.line_total

            print(f"\nLine {i}: {description}")
            print(f"  SKU: {sku}")
            print(f"  Amount: ${line_total}")

            # Categorize
            result = await categorization_service.categorize_line_item(
                vendor="Gordon Food Service",
                sku=sku,
                raw_description=description,
                line_total=line_total,
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

            print(f"  Normalized: {result.normalized_description}")
            print(f"  Category: {result.product_category}")
            print(f"  Account: {result.account_code} - {result.account_name}")
            print(f"  Confidence: {result.confidence:.2%}")
            print(f"  Review needed: {result.requires_review}")

        print()
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Items categorized: 5")
        print(f"Cache hits: {cache_hits}")
        print(f"AI calls: {ai_calls}")
        print(f"Total AI cost: ${float(total_cost):.6f}")
        print(f"Average cost per item: ${float(total_cost / 5):.6f}")

    await sessionmanager.close()


if __name__ == "__main__":
    asyncio.run(main())
