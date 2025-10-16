#!/usr/bin/env python3
"""
Reprocess a receipt with updated OCR/parsing logic.

Usage:
    python scripts/reprocess_receipt.py <receipt_id>

Example:
    python scripts/reprocess_receipt.py acafec2a-00e1-4484-96e7-ccb05e43185f
"""
import sys
import os
import asyncio

# Add parent directory to path so we can import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.worker.tasks.ocr_receipt import reprocess_receipt_task

async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/reprocess_receipt.py <receipt_id>")
        sys.exit(1)

    receipt_id = sys.argv[1]
    print(f"Reprocessing receipt {receipt_id}...")

    result = await reprocess_receipt_task(receipt_id)

    print("\nResult:")
    print(f"  Success: {result.get('success')}")
    if result.get('error'):
        print(f"  Error: {result.get('error')}")
    if result.get('success'):
        print(f"  Vendor: {result.get('vendor')}")
        print(f"  Total: ${result.get('total')}")
        print(f"  Lines: {result.get('line_count')}")
        print(f"  OCR Method: {result.get('ocr_method')}")
        print(f"  OCR Confidence: {result.get('ocr_confidence')}")

if __name__ == "__main__":
    asyncio.run(main())
