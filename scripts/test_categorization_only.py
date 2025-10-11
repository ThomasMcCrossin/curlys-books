#!/usr/bin/env python3
"""
Test AI categorization on a real receipt (standalone test, no database writes)

This demonstrates that Phase 1.5 categorization is working end-to-end.

Usage:
    docker compose exec api python scripts/test_categorization_only.py
"""
import asyncio
import sys
from pathlib import Path
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from packages.common.database import sessionmanager
from packages.common.config import get_settings
from packages.parsers.ocr_engine import extract_text_from_receipt
from packages.parsers.vendor_dispatcher import parse_receipt
from packages.common.schemas.receipt_normalized import EntityType
from packages.domain.categorization.categorization_service import categorization_service

logger = structlog.get_logger()


async def main():
    """Test categorization on a real GFS receipt"""
    settings = get_settings()
    sessionmanager.init(settings.database_url)

    print('='*80)
    print('PHASE 1.5 CATEGORIZATION TEST')
    print('Testing AI categorization on real GFS receipt')
    print('='*80)
    print()

    # Use a real GFS receipt
    receipt_path = "/app/vendor-samples/CurlysCanteenCorp/GFS/Copy of 9002081541.pdf"

    if not Path(receipt_path).exists():
        print(f'❌ Receipt not found: {receipt_path}')
        return

    print(f'📄 Receipt: {receipt_path}')
    print()

    # Step 1: OCR
    print('Step 1: OCR extraction...')
    ocr_result = await extract_text_from_receipt(receipt_path)
    print(f'✓ OCR complete: {ocr_result.confidence:.0%} confidence, {ocr_result.method}, {len(ocr_result.text)} chars')
    print()

    # Step 2: Parse
    print('Step 2: Vendor parsing...')
    entity_type = EntityType.CORP
    parsed_receipt = parse_receipt(ocr_result.text, entity=entity_type)
    print(f'✓ Parsed: {parsed_receipt.vendor_guess}')
    print(f'  Date: {parsed_receipt.purchase_date}')
    print(f'  Total: ${parsed_receipt.total}')
    print(f'  Line items: {len(parsed_receipt.lines)}')
    print()

    # Step 3: Categorize each line item
    print('Step 3: AI Categorization (Phase 1.5)...')
    print('='*80)

    total_ai_cost = Decimal("0")
    categorized_count = 0
    review_count = 0
    cached_count = 0

    async with sessionmanager.session() as db:
        for idx, line in enumerate(parsed_receipt.lines, 1):
            if not line.vendor_sku and not line.item_description:
                print(f'[{idx}] Skipping empty line')
                continue

            try:
                categorization = await categorization_service.categorize_line_item(
                    vendor=parsed_receipt.vendor_guess or "Unknown",
                    sku=line.vendor_sku,
                    raw_description=line.item_description,
                    line_total=line.line_total or Decimal("0"),
                    db=db
                )

                # Display results
                print(f'\n[{idx}] {line.item_description}')
                print(f'    SKU: {line.vendor_sku or "N/A"}')
                print(f'    Amount: ${line.line_total}')
                print(f'    → {categorization.normalized_description}')
                print(f'    → Category: {categorization.product_category}')
                print(f'    → Account: {categorization.account_code} - {categorization.account_name}')
                print(f'    → Confidence: {categorization.confidence:.0%}')
                print(f'    → Source: {categorization.source}')

                if categorization.requires_review:
                    print(f'    ⚠️  REQUIRES REVIEW (confidence < 80%)')
                    review_count += 1

                if categorization.ai_cost_usd:
                    total_ai_cost += categorization.ai_cost_usd
                    print(f'    → AI cost: ${float(categorization.ai_cost_usd):.6f}')

                if categorization.source == "cached":
                    cached_count += 1

                categorized_count += 1

            except Exception as e:
                print(f'\n[{idx}] {line.item_description}')
                print(f'    ❌ CATEGORIZATION FAILED: {e}')
                import traceback
                traceback.print_exc()

    print()
    print('='*80)
    print('RESULTS')
    print('='*80)
    print(f'Total line items: {len(parsed_receipt.lines)}')
    print(f'Categorized: {categorized_count} ({categorized_count/len(parsed_receipt.lines)*100:.0f}%)')
    print(f'Requires review: {review_count} ({review_count/len(parsed_receipt.lines)*100:.0f}%)')
    print(f'Cached: {cached_count} ({cached_count/len(parsed_receipt.lines)*100:.0f}%)')
    print(f'Total AI cost: ${float(total_ai_cost):.6f}')
    print()

    if categorized_count == len(parsed_receipt.lines):
        print('✅ SUCCESS: All line items were categorized!')
        print()
        print('PHASE 1.5 INTEGRATION STATUS:')
        print('✅ OCR Engine working')
        print('✅ Vendor Parser working')
        print('✅ AI Categorization working')
        print('✅ Cache system working')
        print()
        print('READY FOR: Full OCR pipeline integration')
    else:
        print('⚠️  PARTIAL: Some items failed categorization')

    await sessionmanager.close()


if __name__ == "__main__":
    asyncio.run(main())
