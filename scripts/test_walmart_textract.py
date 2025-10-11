#!/usr/bin/env python3
"""Test Walmart parser with AWS Textract (high quality OCR)"""

import sys
import asyncio
sys.path.insert(0, '/app')

from pathlib import Path
from packages.parsers.textract_fallback import TextractFallback
from packages.parsers.vendor_dispatcher import dispatcher
from packages.common.schemas.receipt_normalized import EntityType
from decimal import Decimal

async def main():
    image_path = Path('/app/vendor-samples/Weekofoct10batch/IMG20251011010346.heic')

    print("=" * 80)
    print("WALMART PARSER TEST (AWS TEXTRACT)")
    print("=" * 80)

    # Step 1: OCR with Textract
    print("\n[1/2] Running AWS Textract OCR...")
    textract = TextractFallback()
    result = await textract.extract_text(str(image_path))
    print(f"✓ Textract complete: {len(result.text)} chars, confidence: {result.confidence:.2%}")

    # Save OCR text for analysis
    print(f"\n{'='*80}")
    print(f"OCR TEXT")
    print(f"{'='*80}")
    print(result.text)

    # Step 2: Parse
    print(f"\n{'='*80}")
    print("\n[2/2] Parsing receipt...")
    receipt = dispatcher.dispatch(result.text, entity=EntityType.CORP)

    print(f"\n{'='*80}")
    print(f"PARSING RESULTS")
    print(f"{'='*80}")
    print(f"Vendor: {receipt.vendor_guess}")
    print(f"Date: {receipt.purchase_date}")
    print(f"Receipt #: {receipt.invoice_number}")
    print(f"")
    print(f"Subtotal: ${receipt.subtotal:>10.2f}")
    print(f"Tax:      ${receipt.tax_total:>10.2f}")
    print(f"Total:    ${receipt.total:>10.2f}")
    print(f"")
    print(f"Lines extracted: {len(receipt.lines)}")

    # Calculate line total
    line_total = sum(line.line_total for line in receipt.lines)
    difference = line_total - receipt.subtotal

    print(f"\n{'='*80}")
    print(f"LINE ITEM VALIDATION")
    print(f"{'='*80}")
    print(f"Sum of line totals: ${line_total:.2f}")
    print(f"Expected subtotal:  ${receipt.subtotal:.2f}")
    print(f"Difference:         ${difference:.2f}")

    if abs(difference) <= Decimal("0.02"):
        print(f"✓ VALIDATION PASSED (within ±$0.02 tolerance)")
    else:
        print(f"✗ VALIDATION FAILED (exceeds ±$0.02 tolerance)")

    # Show all lines
    print(f"\n{'='*80}")
    print(f"ALL LINE ITEMS")
    print(f"{'='*80}")
    print(f"{'#':<3} {'Description':<40} {'UPC':<14} {'Amount':>10} {'Tax':>5}")
    print(f"{'-'*80}")

    for i, line in enumerate(receipt.lines, 1):
        upc_display = line.upc or "N/A"
        tax_display = line.tax_flag.value if line.tax_flag else "?"
        desc = line.item_description[:38] + ".." if len(line.item_description) > 40 else line.item_description

        print(f"{i:<3} {desc:<40} {upc_display:<14} ${line.line_total:>8.2f} {tax_display:>5}")

    # Show promotional/negative lines
    promo_lines = [line for line in receipt.lines if line.line_total < 0]
    if promo_lines:
        print(f"\n{'='*80}")
        print(f"PROMOTIONAL DISCOUNTS")
        print(f"{'='*80}")
        for line in promo_lines:
            print(f"  {line.item_description}: ${line.line_total:.2f}")

    print(f"\n{'='*80}")

if __name__ == '__main__':
    asyncio.run(main())
