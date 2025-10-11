#!/usr/bin/env python3
"""
Test Canadian Tire parser with manual text from Q1.2023 receipt

Usage:
    docker compose exec api python scripts/test_canadian_tire.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from decimal import Decimal

from packages.parsers.vendors.canadian_tire_parser import CanadianTireParser
from packages.common.schemas.receipt_normalized import EntityType
from packages.common.database import sessionmanager
from packages.common.config import get_settings
from packages.domain.categorization.categorization_service import categorization_service

logger = structlog.get_logger()


# Manually transcribed from the receipt image
RECEIPT_TEXT = '''
REG #: 01-037 10/2023 11:16:14
OPERATOR #: 0360 Float: 001

ORIG TRN ID:000032303030734940000000010089

ORIG PURCHASE DATE:03/07/2023

-1X063-060B-6 ADAPTER, FAUCET  $ -7.49
-1X063-0740-2 ADAPTER, HOSE 3/4 $ -5.99
-2X063-0806-4          @ $ -13.190 ea.
              COUPLING, GARDEN $ -26.38
-2X063-2140-4          @ $ -1.290 ea.
              CLMP, SS 5/16-7/ $ -2.58
-1X063-1465-8 ADAP, PEAT/ZETA  $ -3.59

My CT 'Honey' Account #:
    **********2444 $  0.00
e-CT 'Honey' Money':
Bonus e-CT $ 52.93

SUBTOTAL            $ -46.03
15% HST             $ -6.90
T O T A L           $ -52.93
eCTM REFUND         $ 52.93

Visit canadiantire.ca or download the
Canadian Tire Mobile App today!

000032303104036000000001006/

HST REG. # 802469674
'''


async def main():
    """Test Canadian Tire parser"""
    settings = get_settings()
    sessionmanager.init(settings.database_url)

    print('='*80)
    print('CANADIAN TIRE PARSER TEST')
    print('='*80)
    print()

    parser = CanadianTireParser()

    # Test detection
    print('Step 1: Format detection...')
    detected = parser.detect_format(RECEIPT_TEXT)
    print(f'✓ Detected as Canadian Tire: {detected}')
    print()

    # Test parsing
    print('Step 2: Parsing...')
    receipt = parser.parse(RECEIPT_TEXT, EntityType.CORP)

    print(f'✓ Vendor: {receipt.vendor_guess}')
    print(f'✓ Invoice: {receipt.invoice_number}')
    print(f'✓ Date: {receipt.purchase_date}')
    print(f'✓ Subtotal: ${receipt.subtotal}')
    print(f'✓ Tax: ${receipt.tax_total}')
    print(f'✓ Total: ${receipt.total}')
    print(f'✓ Line items: {len(receipt.lines)}')
    print()

    if receipt.parsing_errors:
        print(f'⚠ Parsing notes:')
        for error in receipt.parsing_errors:
            print(f'  - {error}')
        print()

    if len(receipt.lines) > 0:
        print('Line Items:')
        print('-'*80)
        for i, line in enumerate(receipt.lines, 1):
            print(f'{i}. {line.item_description}')
            print(f'   SKU: {line.vendor_sku}, Qty: {line.quantity}, Total: ${line.line_total}')
        print()

        # Test categorization on 3 items
        print('='*80)
        print('AI CATEGORIZATION TEST (First 3 real items)')
        print('='*80)
        print()

        async with sessionmanager.session() as db:
            total_cost = Decimal("0")

            for i, line in enumerate([l for l in receipt.lines if l.vendor_sku], 1):
                if i > 3:
                    break

                print(f'[{i}] {line.item_description}')
                print(f'    SKU: {line.vendor_sku}, Amount: ${line.line_total}')

                result = await categorization_service.categorize_line_item(
                    vendor="Canadian Tire",
                    sku=line.vendor_sku,
                    raw_description=line.item_description,
                    line_total=line.line_total,
                    db=db
                )

                print(f'    → {result.normalized_description}')
                print(f'    → {result.product_category} ({result.confidence:.0%})')
                print(f'    → {result.account_code} - {result.account_name}')

                if result.requires_review:
                    print(f'    ⚠ REVIEW REQUIRED')

                if result.ai_cost_usd:
                    total_cost += result.ai_cost_usd
                    print(f'    Cost: ${float(result.ai_cost_usd):.6f}')
                print()

            print(f'Total AI cost: ${float(total_cost):.6f}')
    else:
        print('⚠ No line items parsed!')

    await sessionmanager.close()


if __name__ == "__main__":
    asyncio.run(main())
