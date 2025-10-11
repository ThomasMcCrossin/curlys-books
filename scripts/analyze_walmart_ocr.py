#!/usr/bin/env python3
"""Analyze Walmart OCR text to find discounts and promotions"""

import sys
import asyncio
sys.path.insert(0, '/app')

from pathlib import Path
from packages.parsers.ocr_engine import ocr_engine

async def main():
    image_path = Path('/app/vendor-samples/Weekofoct10batch/IMG20251011010346.heic')

    print("Processing image with Tesseract...")
    result = await ocr_engine.extract_text(str(image_path))

    print('\n=== FULL OCR TEXT ===')
    print(result.text)

    print('\n=== DISCOUNT/PROMO LINES ===')
    for i, line in enumerate(result.text.split('\n'), 1):
        line_upper = line.upper()
        if any(kw in line_upper for kw in ['DISCOUNT', 'PROMO', 'SAVE', 'SAVINGS', 'FOR $', 'MULTI', '2 FOR', '3 FOR']):
            print(f'{i:3d}: {line}')

    print('\n=== BEVERAGE LINES (PEPSI/COKE/DR PEPPER) ===')
    for i, line in enumerate(result.text.split('\n'), 1):
        line_upper = line.upper()
        if any(kw in line_upper for kw in ['PEPSI', 'COKE', 'DR PEPPER', 'MOUNTAIN', 'CANADA DRY', 'BUBLY']):
            print(f'{i:3d}: {line}')

    print(f'\n=== CONFIDENCE: {result.confidence:.2f} ===')

if __name__ == '__main__':
    asyncio.run(main())
