#!/usr/bin/env python3
"""
Test full receipt workflow: OCR → Parse → Categorize → Review Queue
"""
import asyncio
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime
import uuid

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.parsers.ocr_engine import extract_text_from_receipt
from packages.parsers.vendor_dispatcher import parse_receipt
from packages.domain.categorization.categorization_service import categorization_service
from packages.common.schemas.receipt_normalized import EntityType
from packages.common.database import sessionmanager
from packages.common.config import get_settings
from sqlalchemy import text


async def test_workflow():
    """Test full workflow with Walmart receipt"""
    settings = get_settings()
    sessionmanager.init(settings.database_url)

    try:
        print("=" * 80)
        print("WALMART RECEIPT WORKFLOW TEST")
        print("=" * 80)

        # Step 1: OCR
        print("\n[1/5] Running OCR on receipt...")
        receipt_path = "/tmp/walmart_receipt.jpg"

        ocr_result = await extract_text_from_receipt(receipt_path)
        print(f"✓ OCR completed - Confidence: {ocr_result.confidence:.2%}")
        print(f"  Text length: {len(ocr_result.text)} characters")
        print(f"  Method: {ocr_result.method}")

        # Step 2: Parse with vendor dispatcher
        print("\n[2/5] Parsing receipt with vendor dispatcher...")
        receipt = parse_receipt(ocr_result.text, entity=EntityType.CORP)

        print(f"✓ Parsed successfully")
        print(f"  Vendor: {receipt.vendor_guess}")
        print(f"  Date: {receipt.purchase_date}")
        print(f"  Total: ${receipt.total}")
        print(f"  Line items: {len(receipt.lines)}")
        print(f"  Tax: ${receipt.tax_total}")

        # Show first few items
        print("\n  Sample items:")
        for i, line in enumerate(receipt.lines[:5], 1):
            if line.item_description:
                print(f"    {i}. {line.item_description[:50]:<50} ${line.line_total:>7.2f}")

        if len(receipt.lines) > 5:
            print(f"    ... and {len(receipt.lines) - 5} more items")

        # Step 3: Categorize items
        print("\n[3/5] Categorizing line items with AI...")

        async with sessionmanager.session() as db:
            categorized_items = []
            review_items = []

            item_lines = [line for line in receipt.lines if line.item_description]

            for idx, line in enumerate(item_lines, 1):
                desc = line.item_description or "Unknown item"
                print(f"  [{idx}/{len(item_lines)}] {desc[:40]:<40}", end=" ")

                # Call categorization service with correct signature
                categorized = await categorization_service.categorize_line_item(
                    vendor=receipt.vendor_guess or "Walmart",
                    raw_description=desc,
                    line_total=line.line_total,
                    db=db,
                    sku=line.vendor_sku,
                )

                categorized_items.append((line, categorized))

                # Check if needs review
                if categorized.confidence < Decimal("0.80"):
                    review_items.append((line, categorized))
                    print(f"→ {categorized.account_code} ({categorized.confidence:.0%}) ⚠️  REVIEW")
                else:
                    print(f"→ {categorized.account_code} ({categorized.confidence:.0%}) ✓")

            print(f"\n✓ Categorization complete")
            print(f"  Total items: {len(categorized_items)}")
            print(f"  Auto-approved (≥80%): {len(categorized_items) - len(review_items)}")
            print(f"  Needs review (<80%): {len(review_items)}")

            # Step 4: Create receipt record and line items
            print("\n[4/5] Saving receipt to database...")

            # Generate receipt ID
            receipt_id = str(uuid.uuid4())

            # Insert receipt
            insert_receipt_query = text("""
                INSERT INTO curlys_corp.receipts (
                    id, receipt_number, entity, vendor, date,
                    subtotal, tax_total, total, currency,
                    original_file_path, ocr_method, ocr_confidence,
                    created_at
                ) VALUES (
                    :id, :receipt_number, :entity, :vendor, :date,
                    :subtotal, :tax_total, :total, :currency,
                    :original_file_path, :ocr_method, :ocr_confidence,
                    NOW()
                )
            """)

            await db.execute(insert_receipt_query, {
                "id": receipt_id,
                "receipt_number": receipt.invoice_number or "UNKNOWN",
                "entity": "corp",
                "vendor": receipt.vendor_guess or "Walmart",
                "date": receipt.purchase_date,
                "subtotal": float(receipt.subtotal),
                "tax_total": float(receipt.tax_total),
                "total": float(receipt.total),
                "currency": receipt.currency,
                "original_file_path": receipt_path,
                "ocr_method": ocr_result.method,
                "ocr_confidence": float(ocr_result.confidence),
            })

            # Insert line items (only categorized items)
            for idx, (line, categorized) in enumerate(categorized_items, 1):
                requires_review = categorized.confidence < Decimal("0.80")

                insert_line_query = text("""
                    INSERT INTO curlys_corp.receipt_line_items (
                        receipt_id, line_number, sku, description,
                        quantity, unit_price, line_total,
                        product_category, account_code, confidence_score,
                        categorization_source, requires_review, review_status, ai_cost
                    ) VALUES (
                        :receipt_id, :line_number, :sku, :description,
                        :quantity, :unit_price, :line_total,
                        :product_category, :account_code, :confidence_score,
                        :categorization_source, :requires_review, :review_status, :ai_cost
                    )
                """)

                await db.execute(insert_line_query, {
                    "receipt_id": receipt_id,
                    "line_number": idx,
                    "sku": line.vendor_sku,
                    "description": line.item_description,
                    "quantity": float(line.quantity or 1),
                    "unit_price": float(line.unit_price) if line.unit_price else None,
                    "line_total": float(line.line_total),
                    "product_category": categorized.product_category,
                    "account_code": categorized.account_code,
                    "confidence_score": float(categorized.confidence),
                    "categorization_source": categorized.source,
                    "requires_review": requires_review,
                    "review_status": "pending" if requires_review else "approved",
                    "ai_cost": float(categorized.ai_cost_usd) if categorized.ai_cost_usd else 0.0,
                })

            await db.commit()
            print(f"✓ Receipt saved: {receipt_id}")

            # Step 5: Check review queue
            print("\n[5/5] Checking review queue...")

            review_query = text("""
                SELECT COUNT(*) as count
                FROM curlys_corp.view_review_receipt_line_items
                WHERE status = 'pending'
            """)
            result = await db.execute(review_query)
            review_count = result.scalar()

            print(f"✓ Review queue updated")
            print(f"  Total pending items: {review_count}")

            # Show items needing review
            if review_items:
                print("\n" + "=" * 80)
                print("ITEMS REQUIRING REVIEW:")
                print("=" * 80)
                for line, categorized in review_items:
                    print(f"\n• {line.item_description}")
                    print(f"  Amount: ${line.line_total}")
                    print(f"  AI Suggestion: {categorized.product_category} → {categorized.account_code}")
                    print(f"  Confidence: {categorized.confidence:.0%}")
                    print(f"  Normalized: {categorized.normalized_description}")

            print("\n" + "=" * 80)
            print("WORKFLOW COMPLETE!")
            print("=" * 80)
            print(f"\nView review queue at: http://192.168.2.20:3000/review")
            print(f"Receipt ID: {receipt_id}")

    finally:
        await sessionmanager.close()


if __name__ == "__main__":
    asyncio.run(test_workflow())
