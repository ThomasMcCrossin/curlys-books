# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Curly's Books is a multi-entity accounting system for 14587430 Canada Inc. (Curly's Canteen - corp) and Sole Prop (Curly's Sports & Supplements - soleprop). It replaces Wave with accountant-grade books, HST returns, T2/GIFI, and T2125 exports.

**Key Features:** Receipt capture (PWA camera, email-in, Drive sync), hybrid OCR (Tesseract + GPT-4V fallback), vendor-specific parsing templates, bank reconciliation, PAD/autopay matching, Shopify integration, and year-end exports.

**Phase 1 Status (Week 1-2):** ✅ Complete - Parser infrastructure, vendor dispatching, entity-aware repositories, SKU caching. See `docs/PHASE1_PROGRESS.md` for details.

## Development Commands

### Essential Commands (via Make)

```bash
# Initial setup
make dev-setup              # Creates .env from example
make build                  # Build all Docker images
make up                     # Start all services
make migrate                # Run database migrations
make seed                   # Seed initial data (chart of accounts, vendors, GIFI)

# Development workflow
make logs                   # Follow all logs (use ARGS="service_name" for specific)
make restart                # Stop and restart all services
make health                 # Check health of all services

# Testing
make test                   # All tests with coverage (≥85% required)
make test-unit              # Unit tests only (fast)
make test-integration       # Integration tests (requires DB/Redis)
make test-golden            # Golden receipt tests (vendor parsing validation)

# Code quality
make lint                   # Run ruff + mypy (Python) and eslint (TypeScript)
make format                 # Format with black + isort + ruff --fix (Python) and prettier (TypeScript)
make check-imports          # Verify import boundaries (packages/* cannot import apps/*)

# Database operations
make migrate-create ARGS="migration_message"  # Create new migration
make migrate-down           # Rollback one migration
make shell-db               # Open PostgreSQL shell

# Container access
make shell-api              # Bash in API container
make shell-worker           # Bash in worker container
```

### Running Individual Tests

```bash
# Inside API container
docker compose exec api pytest tests/unit/test_specific.py -v
docker compose exec api pytest tests/unit/test_specific.py::test_function_name -v

# With coverage for specific module
docker compose exec api pytest tests/unit/parsers/ -v --cov=packages/parsers --cov-report=term-missing
```

### Direct Service Access

```bash
# API runs on http://localhost:8000
# Web UI runs on http://localhost:3000
# PostgreSQL on localhost:5432
# Redis on localhost:6379

# Manual script execution
docker compose exec api python scripts/import_statements.py statements/file.csv corp
docker compose exec api python packages/parsers/statement_parser.py statements/test.csv
```

## Architecture

### Multi-Entity Separation

The system manages two separate legal entities using **separate PostgreSQL schemas**:
- `curlys_corp` - 14587430 Canada Inc. (Canteen)
- `curlys_soleprop` - Curly's Sports & Supplements
- `shared` - Cross-entity data (users, card registry, audit log, enums)

**Critical:** All database operations must specify the correct schema based on the entity context. Each entity has its own chart of accounts, vendors, receipts, journal entries, and reconciliation data.

### Layered Architecture

```
apps/               # Application layer (I/O, HTTP, UI)
├── api/           # FastAPI backend (routers, middleware)
└── web/           # Next.js PWA (receipt capture, review UI)

services/          # Background processing (async tasks)
└── worker/        # Celery workers (OCR, parsing, matching, Shopify sync)

packages/          # Reusable business logic and utilities
├── domain/        # Pure business logic (NO I/O dependencies)
│   ├── accounting/       # Journal entries, posting rules, HST calculator, CCA
│   └── validation/       # Receipt validation, matching rules
├── parsers/       # OCR engine, statement parser, vendor templates
├── matching/      # Bank matcher, PAD matcher, duplicate detector
└── common/        # Shared schemas (Pydantic), database, config, errors
```

### Import Boundaries (Enforced)

**Rules:**
1. `apps/*` can import from `packages/*` and `services/*`
2. `packages/*` **CANNOT** import from `apps/*` or `services/*`
3. Apps **CANNOT** import from each other (`apps.api` ↔ `apps.web`)
4. `packages/domain` is **pure** - no SQLAlchemy, Redis, httpx, Celery

Verify with: `make check-imports`

### Receipt Processing Flow

1. **Upload** → `apps/api/routers/receipts.py` saves to `/srv/curlys-books/objects/{entity}/{receipt_id}/original.{ext}`
2. **Queue OCR** → Celery task `services/worker/tasks/ocr_receipt.py`
3. **OCR** → Tesseract first (confidence threshold 90%), GPT-4V fallback if low confidence
4. **Vendor Parsing** → `packages/parsers/vendor_dispatcher.py` routes to vendor-specific template
5. **Normalization** → Output as `ReceiptNormalized` schema (packages/common/schemas/receipt_normalized.py)
6. **Classification** → Maps SKUs/items to GL accounts, determines tax treatment
7. **Review** → If auto-post confidence < threshold, send to review queue
8. **Posting** → Creates journal entry in entity schema, links to receipt

### Bank Reconciliation Matching

**Matching tolerances** (configured in .env):
- Amount: ±0.5% or ±$0.02 (whichever is larger)
- Date window: -3 to +5 days from receipt date

**Workflow:**
1. Import CIBC CSV → `packages/parsers/statement_parser.py` normalizes to `BankLine`
2. Extract merchant from description (patterns in `statement_parser.py:71-76`)
3. Match to receipts → `packages/matching/bank_matcher.py`
4. PAD/Autopay → Separate workflow via `packages/matching/pad_matcher.py` (Net 7, Net 14, 15th next month)
5. Mark receipt as `matched`, update `matched_bank_line_id`

### Schemas and Validation

**Core schemas** (Pydantic v2):
- `ReceiptNormalized` - Canonical receipt format after OCR/parsing (packages/common/schemas/receipt_normalized.py)
- `PostingDecision` - GL account mappings and tax treatment (TODO: not yet implemented)
- `JournalEntry` - Double-entry journal entry (TODO: not yet implemented)

**Validation:**
- Line items must sum to subtotal (±$0.02 tolerance)
- Subtotal + tax_total must equal total (±$0.02 tolerance)
- All amounts are `Decimal` (never float)

### Database Migrations

Located in `infra/db/alembic/versions/`. Alembic config: `alembic.ini` (script_location: `infra/db/migrations`).

**Schema structure:**
- `001_initial_schema.py` creates tables for **both** entity schemas using `create_entity_tables(schema_name)` helper
- Migrations run against the default database connection, but create objects in multiple schemas

**Important:** When creating new tables/columns, ensure they are created in the correct schema context. Refer to `infra/db/alembic/versions/001_initial_schema.py:19-100` for examples.

### HST/Tax Handling

**Nova Scotia HST rate change:** 15% before 2025-04-01, 14% after (implemented in `packages/domain/accounting/hst_calculator.py` - TODO).

**Tax flags:**
- `Y` = Taxable (HST applicable)
- `Z` = Zero-rated (0% but eligible for ITC)
- `N` = Exempt (no HST, no ITC)

**ITC (Input Tax Credit) tracking:** Line-level tax amounts stored in `ReceiptLine.tax_amount` for HST return reconciliation.

### Golden Receipt Tests

Vendor-specific parsing validation using known good receipts in `tests/fixtures/golden_receipts/`. Each vendor folder contains:
1. Sample receipt image
2. Expected `ReceiptNormalized` JSON
3. Expected `PostingDecision` JSON
4. Expected `JournalEntry` JSON

**Priority vendors:** Capital, GFS, Costco, Superstore, Pharmasave, Wholesale Club.

Run with: `make test-golden`

### Reimbursement Workflow (Monday Batch)

**Automated batch preparation:** Every Monday 09:00, group owner-paid receipts by person + card.

**Approval flow:**
1. Review batch at `https://books.curlys.ca/reimbursements`
2. Uncheck outliers, approve → generates Payment Checklist
3. Execute bill payments via CIBC
4. Mark batch as "Paid" with payment date

**Auto-reconciliation:** Bank import matches bill payment transactions, clears "Due to Shareholder" (account TBD).

### Cloudflare Access Authentication

**Production:** All access protected by Cloudflare Tunnel + Access (Google Workspace SSO + 2FA).

**Development:** Set `SKIP_AUTH_VALIDATION=true` in `.env` to bypass middleware (apps/api/middleware/auth_cloudflare.py).

**Tunnel ID:** `ab0fcffa-7192-4ee6-a361-5198d144d708`

### Storage Paths

- **Receipt objects:** `/srv/curlys-books/objects/{entity}/{receipt_id}/`
  - `original.{ext}` - Original upload
  - `normalized.jpg` - Preprocessed for OCR (deskewed, cropped)
  - `thumbnail.jpg` - Web UI preview
- **Receipt library:** `/library/{curlys_corp,curlys_soleprop}/Receipts/` - Organized by date/vendor
- **Drive backups:** Google Drive 2TB, 7-year retention

### Logging

**Structured logging** via `structlog` (JSON output):
```python
import structlog
logger = structlog.get_logger()
logger.info("event_name", key1=value1, key2=value2)
```

**Log levels:** DEBUG, INFO, WARNING, ERROR (configured via `LOG_LEVEL` env var).

### Testing Standards

**Coverage requirements:**
- `packages/domain`: ≥85%
- `packages/parsers`: ≥85%
- `services/worker`: ≥85%

**Markers:**
- `@pytest.mark.unit` - Fast, isolated tests
- `@pytest.mark.integration` - Requires DB/Redis
- `@pytest.mark.golden` - Vendor parsing validation
- `@pytest.mark.slow` - OCR, external APIs

**Fixtures:** Use `tests/fixtures/` for sample data. Database fixtures use `asyncpg` for test isolation.

## Common Patterns

### Entity Context in Routes

```python
from packages.common.schemas.receipt_normalized import EntityType

@router.post("/upload")
async def upload_receipt(
    entity: EntityType = Form(...),  # "corp" or "soleprop"
    db: AsyncSession = Depends(get_db_session),
):
    # Use entity.value to get string "corp" or "soleprop"
    schema_name = f"curlys_{entity.value}"
```

### Duplicate Detection

**Content hash:** SHA256 of original file (packages/common/schemas/receipt_normalized.py:138)
**Perceptual hash:** pHash for image similarity (packages/common/schemas/receipt_normalized.py:139)

Check both before saving. Perceptual hash allows detection of rescanned/rephotographed receipts.

### Vendor-Specific Parsing

Located in `packages/parsers/vendor_dispatcher.py` (TODO: not yet implemented). Uses `parsing_quirks` JSONB field in `vendors` table to store vendor-specific rules:
- Line item regex patterns
- SKU extraction logic
- Date format variations
- Multi-page receipt handling

### Decimal Precision

**Always use `Decimal` for currency amounts.** Never `float`.

```python
from decimal import Decimal

subtotal = Decimal("123.45")
tax = subtotal * Decimal("0.15")  # NOT 0.15 (float)
```

### Async Database Sessions

```python
from packages.common.database import get_db_session
from sqlalchemy import select

async def example(db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Receipt).where(Receipt.entity == "corp"))
    receipts = result.scalars().all()
```

## Project-Specific Notes

- **Phase 0 complete** (per git log): Docker stack, migrations, API stubs operational
- **Phase 1 in progress:** CSV parser done, OCR pipeline in development, basic web UI pending
- **Tesseract confidence threshold:** 90% (configurable via `TESSERACT_CONFIDENCE_THRESHOLD`)
- **Receipt number format:** Auto-generated, format TBD (currently UUID in `receipts.receipt_number`)
- **Shopify integration:** Dual stores (Canteen corp, Sports soleprop) - API stubs exist but not implemented
- **Year-end dates:** Corp = May 31, Sole Prop = Dec 31

## Known TODOs (from code comments)

- `apps/api/routers/receipts.py:68` - Duplicate detection query not implemented
- `apps/api/routers/receipts.py:128` - Receipt lookup not implemented
- `apps/api/routers/receipts.py:148` - Receipt listing not implemented
- `apps/api/routers/receipts.py:165` - Approval workflow not implemented
- `apps/api/routers/receipts.py:200` - File retrieval not implemented
- `apps/api/main.py:147` - Redis health check not implemented
- `packages/parsers/vendor_dispatcher.py` - Not yet implemented
- HST calculator, CCA schedule, posting rules, journal entry creation - All TODO

## File Locations Reference

- **Migrations:** `infra/db/alembic/versions/`
- **Golden receipts:** `tests/fixtures/golden_receipts/{vendor}/`
- **Vendor samples:** `tests/fixtures/vendor_receipts/` (added per recent commit)
- **OCR engine:** `packages/parsers/ocr_engine.py` (TODO: not yet created)
- **API main:** `apps/api/main.py`
- **Receipt upload:** `apps/api/routers/receipts.py`
- **Statement parser:** `packages/parsers/statement_parser.py`
- **Config:** `packages/common/config.py`
- **Database:** `packages/common/database.py`
- **Schemas:** `packages/common/schemas/`
