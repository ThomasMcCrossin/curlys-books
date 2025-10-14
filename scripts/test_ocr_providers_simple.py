#!/usr/bin/env python3
"""
Simple test for OCR provider refactor.

Tests that the new provider architecture works correctly.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.parsers.ocr import extract_text_from_receipt
from packages.parsers.vendor_dispatcher import parse_receipt
from packages.common.schemas.receipt_normalized import EntityType


async def test_ocr_providers():
    """Test OCR provider architecture with Walmart receipt"""

    receipt_path = "/srv/curlys-books/objects/corp/acafec2a-00e1-4484-96e7-ccb05e43185f/original.heic"

    print("=" * 80)
    print("OCR PROVIDER REFACTOR TEST - WALMART RECEIPT")
    print("=" * 80)
    print()

    # Test OCR
    print("Testing new OCR provider architecture...")
    ocr_result = await extract_text_from_receipt(receipt_path)

    print(f"✅ Provider used: {ocr_result.method}")
    print(f"✅ Confidence: {ocr_result.confidence:.2%}")
    print(f"✅ Text extracted: {len(ocr_result.text)} chars")
    print(f"✅ Bounding boxes: {len(ocr_result.bounding_boxes)}")
    print()

    # Test parsing
    print("Testing vendor parsing...")
    parsed = parse_receipt(ocr_result.text, entity=EntityType.CORP)

    print(f"✅ Vendor detected: {parsed.vendor_guess}")
    print(f"✅ Date: {parsed.purchase_date}")
    print(f"✅ Total: ${parsed.total}")
    print(f"✅ Line items: {len(parsed.lines)}")
    print()

    # Show some items
    print("Sample line items:")
    for i, line in enumerate(parsed.lines[:8], 1):
        desc = (line.item_description or "N/A")[:35]
        qty = line.quantity or 1
        price = line.line_total or 0
        print(f"  {i:2d}. {desc:35s} {qty:>3} x ${price:>6.2f}")
    print()

    # Verify refactor success
    print("=" * 80)
    print("VERIFICATION")
    print("=" * 80)

    checks = [
        (ocr_result.method == "textract", "Used Textract for HEIC image"),
        (ocr_result.confidence > 0.95, f"High confidence ({ocr_result.confidence:.2%})"),
        (len(ocr_result.bounding_boxes) > 0, f"Has bounding boxes ({len(ocr_result.bounding_boxes)})"),
        (parsed.vendor_guess == "Walmart", "Correct vendor detected"),
        (len(parsed.lines) > 30, f"Extracted {len(parsed.lines)} line items"),
        (float(parsed.total) == 204.03, f"Correct total: ${parsed.total}"),
    ]

    passed = sum(1 for check, _ in checks if check)
    total = len(checks)

    for check, desc in checks:
        status = "✅" if check else "❌"
        print(f"{status} {desc}")

    print()
    print(f"Result: {passed}/{total} checks passed")
    print()

    if passed == total:
        print("🎉 OCR PROVIDER REFACTOR TEST PASSED!")
        print()
        print("Key improvements:")
        print("  - Tesseract is now optional")
        print("  - Clean provider pattern architecture")
        print("  - Configuration-driven strategy")
        print("  - Lazy loading of providers")
        return 0
    else:
        print("⚠️  Some checks failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(test_ocr_providers())
    sys.exit(exit_code)
