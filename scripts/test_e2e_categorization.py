#!/usr/bin/env python3
"""
End-to-end test of receipt processing with AI categorization

This script:
1. Processes a real GFS receipt through the OCR pipeline
2. Verifies that categorization happens automatically
3. Checks that results are stored in receipt_line_items

Usage:
    docker compose exec api python scripts/test_e2e_categorization.py
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from sqlalchemy import text
from celery import Celery

from packages.common.database import sessionmanager
from packages.common.config import get_settings

logger = structlog.get_logger()


async def main():
    """Test end-to-end receipt processing with categorization"""
    settings = get_settings()
    sessionmanager.init(settings.database_url)

    print('='*80)
    print('END-TO-END RECEIPT CATEGORIZATION TEST')
    print('='*80)
    print()

    # Use a real GFS receipt
    receipt_path = "/app/vendor-samples/CurlysCanteenCorp/GFS/Copy of 9002081541.pdf"

    if not Path(receipt_path).exists():
        print(f'❌ Receipt not found: {receipt_path}')
        print()
        print('Looking for available GFS receipts...')
        gfs_dir = Path("/app/vendor-samples/CurlysCanteenCorp/GFS")
        if gfs_dir.exists():
            for receipt in gfs_dir.glob("*.pdf"):
                print(f'  Found: {receipt}')
                receipt_path = str(receipt)
                break
        else:
            print('❌ No GFS receipts found')
            return

    print(f'📄 Processing receipt: {receipt_path}')
    print()

    # Generate receipt ID
    receipt_id = str(uuid4())
    entity = "corp"

    print(f'Receipt ID: {receipt_id}')
    print(f'Entity: {entity}')
    print()

    # Create initial receipt record in database
    print('Step 1: Creating receipt record in database...')
    async with sessionmanager.session() as db:
        await db.execute(
            text(f"""
                INSERT INTO curlys_{entity}.receipts (
                    id,
                    status,
                    file_path,
                    upload_source,
                    created_at
                ) VALUES (
                    :receipt_id,
                    'pending',
                    :file_path,
                    'test',
                    NOW()
                )
            """),
            {
                "receipt_id": receipt_id,
                "file_path": receipt_path
            }
        )
        await db.commit()
    print('✓ Receipt record created')
    print()

    # Process receipt (this will trigger categorization)
    print('Step 2: Processing receipt with OCR + Categorization...')
    print('(Running synchronously for testing, not via Celery queue)')
    print('-'*80)

    try:
        # Import here to run in worker context
        from packages.parsers.ocr_engine import extract_text_from_receipt
        from packages.parsers.vendor_dispatcher import parse_receipt
        from packages.common.schemas.receipt_normalized import EntityType
        from packages.domain.categorization.categorization_service import categorization_service

        # Step 2a: OCR
        ocr_result = await extract_text_from_receipt(receipt_path)
        print(f'✓ OCR complete: {ocr_result.confidence:.0%} confidence, {len(ocr_result.text)} chars')

        # Step 2b: Parse
        entity_type = EntityType.CORP if entity == 'corp' else EntityType.SOLEPROP
        parsed_receipt = parse_receipt(ocr_result.text, entity=entity_type)
        print(f'✓ Parsed: {parsed_receipt.vendor_guess}, ${parsed_receipt.total}, {len(parsed_receipt.lines)} lines')

        # Step 2c: Categorize each line
        print()
        print('Categorizing line items...')
        categorized_lines = []
        total_ai_cost = Decimal("0")

        async with sessionmanager.session() as db:
            for idx, line in enumerate(parsed_receipt.lines, 1):
                if not line.sku and not line.description:
                    categorized_lines.append({"line": line, "categorization": None})
                    continue

                try:
                    categorization = await categorization_service.categorize_line_item(
                        vendor=parsed_receipt.vendor_guess or "Unknown",
                        sku=line.sku,
                        raw_description=line.description,
                        line_total=line.line_total or Decimal("0"),
                        db=db
                    )

                    categorized_lines.append({"line": line, "categorization": categorization})

                    if categorization.ai_cost_usd:
                        total_ai_cost += categorization.ai_cost_usd

                    print(f'  [{idx}] {line.description[:40]:40} → {categorization.product_category:20} '
                          f'({categorization.confidence:.0%}) [{categorization.source}]')

                except Exception as e:
                    print(f'  [{idx}] {line.description[:40]:40} → FAILED: {e}')
                    categorized_lines.append({"line": line, "categorization": None})

        print()
        print(f'✓ Categorization complete: ${float(total_ai_cost):.6f} total cost')
        print()

        # Step 2d: Store results
        print('Storing results in database...')
        async with sessionmanager.session() as db:
            # Update receipt
            await db.execute(
                text(f"""
                    UPDATE curlys_{entity}.receipts
                    SET
                        status = 'processed',
                        vendor_name = :vendor,
                        total_amount = :total,
                        ocr_confidence = :ocr_confidence,
                        ocr_method = :ocr_method,
                        extracted_text = :extracted_text,
                        purchase_date = :purchase_date,
                        updated_at = NOW()
                    WHERE id = :receipt_id
                """),
                {
                    "receipt_id": receipt_id,
                    "vendor": parsed_receipt.vendor_guess,
                    "total": parsed_receipt.total,
                    "ocr_confidence": ocr_result.confidence,
                    "ocr_method": ocr_result.method,
                    "extracted_text": ocr_result.text[:10000],
                    "purchase_date": parsed_receipt.purchase_date,
                }
            )

            # Insert line items
            for line_num, categorized_line in enumerate(categorized_lines, start=1):
                line = categorized_line["line"]
                categorization = categorized_line.get("categorization")

                if categorization:
                    await db.execute(
                        text(f"""
                            INSERT INTO curlys_{entity}.receipt_line_items (
                                receipt_id, line_number, sku, description,
                                quantity, unit_price, line_total,
                                account_code, product_category, confidence_score,
                                categorization_source, requires_review, ai_cost
                            ) VALUES (
                                :receipt_id, :line_number, :sku, :description,
                                :quantity, :unit_price, :line_total,
                                :account_code, :product_category, :confidence_score,
                                :categorization_source, :requires_review, :ai_cost
                            )
                        """),
                        {
                            "receipt_id": receipt_id,
                            "line_number": line_num,
                            "sku": line.sku,
                            "description": line.description,
                            "quantity": line.quantity,
                            "unit_price": line.unit_price,
                            "line_total": line.line_total,
                            "account_code": categorization.account_code,
                            "product_category": categorization.product_category,
                            "confidence_score": categorization.confidence,
                            "categorization_source": categorization.source,
                            "requires_review": categorization.requires_review,
                            "ai_cost": categorization.ai_cost_usd,
                        }
                    )
                else:
                    await db.execute(
                        text(f"""
                            INSERT INTO curlys_{entity}.receipt_line_items (
                                receipt_id, line_number, sku, description,
                                quantity, unit_price, line_total,
                                requires_review, categorization_source
                            ) VALUES (
                                :receipt_id, :line_number, :sku, :description,
                                :quantity, :unit_price, :line_total,
                                :requires_review, :categorization_source
                            )
                        """),
                        {
                            "receipt_id": receipt_id,
                            "line_number": line_num,
                            "sku": line.sku,
                            "description": line.description,
                            "quantity": line.quantity,
                            "unit_price": line.unit_price,
                            "line_total": line.line_total,
                            "requires_review": True,
                            "categorization_source": "failed",
                        }
                    )

            await db.commit()

        print('✓ Results stored in database')
        print()
        print('-'*80)
        print()

    except Exception as e:
        print(f'❌ Exception during processing: {e}')
        import traceback
        traceback.print_exc()
        return

    # Verify categorization results in database
    print('Step 3: Verifying categorization results...')
    print('-'*80)

    async with sessionmanager.session() as db:
        result = await db.execute(
            text(f"""
                SELECT
                    line_number,
                    sku,
                    description,
                    line_total,
                    account_code,
                    product_category,
                    confidence_score,
                    categorization_source,
                    requires_review,
                    ai_cost
                FROM curlys_{entity}.receipt_line_items
                WHERE receipt_id = :receipt_id
                ORDER BY line_number
            """),
            {"receipt_id": receipt_id}
        )

        lines = result.fetchall()

        if not lines:
            print('⚠️  No line items found in database!')
            print()
            return

        print(f'Found {len(lines)} line items:')
        print()

        total_ai_cost = Decimal("0")
        categorized_count = 0
        review_count = 0

        for line in lines:
            print(f'[{line.line_number}] {line.description}')
            print(f'    SKU: {line.sku or "N/A"}')
            print(f'    Amount: ${line.line_total}')

            if line.account_code:
                print(f'    → Category: {line.product_category}')
                print(f'    → Account: {line.account_code}')
                print(f'    → Confidence: {float(line.confidence_score):.0%}')
                print(f'    → Source: {line.categorization_source}')

                if line.requires_review:
                    print(f'    ⚠️  REQUIRES REVIEW')
                    review_count += 1

                if line.ai_cost:
                    total_ai_cost += line.ai_cost
                    print(f'    → AI cost: ${float(line.ai_cost):.6f}')

                categorized_count += 1
            else:
                print(f'    ⚠️  NOT CATEGORIZED (source: {line.categorization_source})')

            print()

        print('='*80)
        print('SUMMARY')
        print('='*80)
        print(f'Total lines: {len(lines)}')
        print(f'Categorized: {categorized_count} ({categorized_count/len(lines)*100:.0f}%)')
        print(f'Requires review: {review_count} ({review_count/len(lines)*100:.0f}%)')
        print(f'Total AI cost: ${float(total_ai_cost):.6f}')
        print()

        if categorized_count == len(lines):
            print('✅ SUCCESS: All line items were categorized!')
        elif categorized_count > 0:
            print('⚠️  PARTIAL: Some line items were categorized')
        else:
            print('❌ FAILURE: No line items were categorized')

    await sessionmanager.close()


if __name__ == "__main__":
    asyncio.run(main())
