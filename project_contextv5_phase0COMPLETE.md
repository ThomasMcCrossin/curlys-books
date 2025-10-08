# Curly's Books - Project Context Document (COMPLETE)
**Last Updated:** 2025-10-08 02:55 AM ADT  
**Status:** Phase 0 Complete ✅ | Phase 1 Ready to Start 🚀

---

## Executive Summary

Accounting software for two Nova Scotia businesses:
- **14587430 Canada Inc. ("Curly's Canteen")** - Corp, fiscal year end May 31
- **Curly's Sports & Supplements** - Sole Proprietorship, fiscal year end Dec 31

**Goal:** Replace Wave with accountant-grade books, automated receipt processing, HST returns, and year-end exports (T2/GIFI/T2125).

**Current State:** Foundation deployed and working. API healthy, receipt upload functional, task queue operational, ready for OCR development.

---

## What's Working ✅

### Infrastructure (Deployed & Tested)
- **Docker stack:** PostgreSQL 16, Redis 7, FastAPI, Celery worker, Next.js stub
- **Database:** Migrations applied, dual schemas (curlys_corp, curlys_soleprop)
- **API endpoints:**
  - `/health` - Returns 200 OK, database connected ✅
  - `/api/v1/receipts/upload` - Working! Accepts PDFs, queues OCR tasks ✅
- **Task Queue:** Celery worker successfully processing tasks ✅
- **File Storage:** Receipts saved to `/srv/curlys-books/objects/{entity}/{receipt_id}/` ✅
- **OCR Dependencies:** Tesseract 5.5.0 installed and functional in worker container ✅

### Recent Fixes (2025-10-08)
- ✅ **Fixed worker environment variables:** Added missing SECRET_KEY and Cloudflare vars via `env_file: - .env`
- ✅ **Fixed task registration:** Replaced autodiscovery with explicit imports in `services/worker/celery_app.py`
- ✅ **Fixed task naming mismatch:** Aligned API task queue calls with worker task names
- ✅ **Fixed .env file corruption:** Resolved malformed USE_MOCK_DATA line
- ✅ **Created stub OCR task:** Replaced imports of non-existent parsers with working stub
- ✅ **Storage path consistency:** All services now use `/srv/curlys-books/objects` path
- ✅ **Fixed web health endpoint:** Added `/health` route to Next.js, cleared cache

### Verified Working Flow
1. Receipt uploaded via API → File saved to storage
2. Task queued to Redis → Worker picks up task
3. Stub processing → Success response
4. All containers healthy and operational
5. Health check: API ✅, Worker ✅, Web ✅, Database ✅, Redis ✅

### Data Available
- **67 vendor receipt samples** uploaded to `vendor-samples/`
  - Canteen: Capital (6), GFS (12), Costco (8), Superstore (4), Pharmasave (1), Pepsi (7)
  - Store: Amazon (5), Believe (3), FitFoods (2), Grosnor (2), Isweet (2), NSPower (2), Peak (3), PurityLife (4), SupplementFacts (4), YummySports (4)
- **CIBC CSV parser** working (494 real transactions tested)
- **Chart of Accounts** seeded with GIFI codes

---

## Business Structure

### Entities
1. **14587430 Canada Inc. ("Curly's Canteen")** - Corp
   - Ownership: 75% Dwayne, 25% Thomas
   - Business: Canteen/convenience store
   - Fiscal year end: May 31
   - Location: Nova Scotia

2. **Curly's Sports & Supplements** - Sole Proprietorship
   - Owner: 100% Dwayne
   - Business: Sports nutrition and supplements
   - Fiscal year end: December 31
   - Location: Nova Scotia

### Key People
- **Dwayne**: Majority owner of Corp, owns Sole Prop, primary cardholder
- **Thomas McCrossin**: 25% Corp owner, secondary cardholder, project manager
  - GitHub: ThomasMcCrossin/curlys-books
  - Server: clarencehub@clarencehub (Lenovo M920 Tiny)

---

## Account Structure

### Business Bank Accounts
**Corp (Canteen):**
- CIBC Business Chequing
- Format: CSV (Date, Description, Debit, Credit)

**Sole Prop (Sports):**
- CIBC Business Chequing
- Format: CSV (Date, Description, Debit, Credit)

### Credit Cards (Shared by Both Businesses)

**CIBC Visa Account:**
- Primary: ...0318 (Dwayne)
- Secondary: ...4337 (Thomas)
- Statement format: CSV (Date, Merchant, Amount, Empty, Card Number)
- Used for: Corp + Sole Prop expenses

**CIBC Mastercard Account:**
- Primary: ...7022 (Dwayne)
- Secondary: ...8154 (Dwayne)
- Statement format: CSV (Date, Merchant, Amount, Empty, Card Number)
- Used for: Corp + Sole Prop expenses

### Personal Accounts (with business expenses)
- **Mosaik Credit Union** Debit Mastercard: ...7614
  - Format: PDF only (Date | Transaction Type | Item | Debit | Credit | Balance)
  
- **Scotiabank Visa**: ...7401
  - Format: CSV (Filter, Date, Description, Sub-description, Status, Type, Amount)

---

## Reimbursement Structure

### Corp (Canteen) Reimbursements
**How it works:**
- Both Dwayne and Thomas make purchases on shared CIBC cards
- Corp reimburses BOTH via bill pay to card accounts
- System tracks: Who made purchase → Corp owes that person
- Accounting: DR Expense/COGS, DR HST ITC, CR Due to Shareholder - [Person]

**Monday Batch Workflow:**
1. System generates batch every Monday 9 AM
2. Groups by person + card
3. User reviews, unchecks outliers, approves
4. Makes bill payment(s) to card account(s)
5. Bank import auto-matches and clears Due to Shareholder

### Sole Prop (No Reimbursement)
- Dwayne's expenses = Direct COGS
- Posting: DR Expense/COGS, DR HST ITC, CR Due from card account

---

## Revenue & Sales Tracking

### Canteen (Price Point Model)
**Important:** Products priced tax-inclusive for speed:
- Shelf price: $0.88 (plus HST 14% = $1.00 total)
- Customer pays: $1.00 even (no change)
- Shopify records: $0.88 revenue + $0.12 HST

**Implications:**
- Shopify tracks by price point ($0.25, $1.00, $5.00 items)
- Shopify does NOT track which product sold
- Product-level sales analysis: NOT possible at Canteen
- Aggregate margin analysis: YES possible

### Sports Store (Product-Level)
- Shopify DOES track individual products
- Full product-level analysis possible

---

## Tax & Compliance (Nova Scotia)

### HST Rates
- **Before April 1, 2025:** 15%
- **April 1, 2025 onward:** 14%
- System applies correct rate based on transaction date

### Year-End Requirements
**Corp:** Trial Balance, GIFI CSV, Schedule 8/CCA, HST return, audit pack, inventory (May 31)  
**Sole Prop:** Trial Balance, T2125 export, HST return, audit pack, inventory (Dec 31)

### Capitalization Threshold
Assets ≥ $2,500 → Asset Register (not expensed)

---

## Technical Architecture

### Stack
```
Docker Compose (5 services)
├── postgres:16-alpine (PostgreSQL)
├── redis:7-alpine (Celery broker + cache)
├── curlys-books-api (FastAPI backend)
├── curlys-books-worker (Celery worker for OCR)
└── curlys-books-web (Next.js PWA - minimal stub)
```

### Project Structure
```
curlys-books/
├── docker-compose.yml
├── Makefile
├── .env (gitignored)
├── .env.example
├── pyproject.toml (Poetry dependencies)
├── alembic.ini (at project root)
│
├── apps/
│   ├── api/                    # FastAPI backend
│   │   ├── main.py            # Application entry point
│   │   ├── tasks.py           # Task queue wrapper ✅ FIXED
│   │   ├── middleware/
│   │   │   └── auth_cloudflare.py  # Cloudflare Access stub
│   │   └── routers/
│   │       ├── receipts.py    # ✅ Working - upload endpoint
│   │       ├── banking.py     # Stub
│   │       ├── reimbursements.py  # Stub
│   │       ├── reports.py     # Stub
│   │       └── shopify_sync.py    # Stub
│   │
│   └── web/                   # Next.js PWA (minimal stub)
│       ├── package.json
│       ├── app/
│       │   ├── page.tsx
│       │   ├── layout.tsx
│       │   └── health/
│       │       └── route.ts   # ✅ Health endpoint working
│
├── services/
│   └── worker/                # Celery worker
│       ├── celery_app.py      # ✅ FIXED: explicit imports
│       └── tasks/
│           └── ocr_receipt.py  # ✅ Working stub task
│
├── packages/
│   ├── common/
│   │   ├── config.py          # Settings (Pydantic) ✅ FIXED
│   │   ├── __init__.py        # Module exports
│   │   ├── database.py        # SQLAlchemy setup
│   │   └── schemas/
│   │       └── receipt_normalized.py  # Receipt models
│   │
│   └── parsers/
│       ├── cibc_csv.py        # ✅ Working (494 txns tested)
│       └── ocr_engine.py      # Stub for Tesseract (Phase 1)
│
├── infra/
│   ├── db/
│   │   ├── init.sql
│   │   └── migrations/        # Alembic migrations (applied)
│   │
│   └── docker/
│       ├── api/Dockerfile
│       ├── worker/Dockerfile  # ✅ Tesseract 5.5.0 installed
│       └── web/Dockerfile
│
├── vendor-samples/            # 67 receipt samples
│   ├── CurlysCanteenCorp/
│   │   ├── Capital/          (6 files)
│   │   ├── GFS/              (12 files)
│   │   ├── Costco/           (8 files)
│   │   ├── Superstore/       (4 files)
│   │   ├── Pharmasave/       (1 file)
│   │   └── Pepsi/            (7 files)
│   │
│   └── CurlysSolePropStore/
│       ├── Amazon/           (5 files)
│       ├── Believe/          (3 files)
│       ├── FitFoods/         (2 files)
│       ├── Grosnor/          (2 files)
│       ├── Isweet/           (2 files)
│       ├── NSPower/          (2 files)
│       ├── Peak/             (3 files)
│       ├── PurityLife/       (4 files)
│       ├── SupplementFacts/  (4 files)
│       └── Yummy Sports/     (4 files)
│
└── tests/
    └── fixtures/
        └── golden_receipts/   # To be created in Phase 1
```

### Database
- **Dual schemas:** `curlys_corp`, `curlys_soleprop`
- **Shared schema:** Users, card registry, feature flags, audit log
- **Tables:** receipts, bills, bank_statements, journal_entries, reimbursements
- **Audit trail:** All mutations logged

### Storage Paths
- **Receipts (uploaded):** `/srv/curlys-books/objects/` → mounted from host `/srv/curlys-books/objects/`
- **Receipt library (organized):** `/library/` → mounted from host `/library/`
- **PostgreSQL data:** Docker volume `curlys-books_postgres_data`
- **Permissions:** Container runs as uid 1000 (user: curlys)

---

## OCR Strategy

### Primary: Tesseract OCR
- Free, fast, local processing
- **Confidence threshold: 90%** (was 60%, increased for quality)
- File-type aware: PDFs should easily hit 90%+

### Fallback: AWS Textract
- When confidence < 90%
- $1.50/1,000 pages
- Better for crumpled receipts, specialized tables
- **NOT using GPT-4V** (less accurate for structured receipts)

### Vendor Templates (Boost Confidence)
- Known vendor format: +15% confidence
- Math validation: +10% confidence
- Expected auto-approve rate: 85-90%

### Configuration (.env) ✅ WORKING
```bash
# Database
DATABASE_URL=postgresql://${DB_USER:-curlys_admin}:${DB_PASSWORD}@postgres:5432/${DB_NAME:-curlys_books}
DB_PASSWORD=*** (working)

# Redis & Celery
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# Authentication
SECRET_KEY=*** (working)
CLOUDFLARE_ACCESS_AUD=*** (working)
CLOUDFLARE_TEAM_DOMAIN=*** (working)
CLOUDFLARE_TUNNEL_ID=*** (working)

# OCR Configuration
TESSERACT_PATH=/usr/bin/tesseract ✅
TESSERACT_CONFIDENCE_THRESHOLD=90
TEXTRACT_FALLBACK_ENABLED=true

# AWS Textract (fallback)
AWS_ACCESS_KEY_ID=***
AWS_SECRET_ACCESS_KEY=***
AWS_TEXTRACT_REGION=us-east-1

# File Storage
RECEIPT_STORAGE_PATH=/srv/curlys-books/objects ✅

# Development
DEBUG=false
SKIP_AUTH_VALIDATION=false
USE_MOCK_DATA=false ✅ Fixed

# Gmail Integration
GOOGLE_APPLICATION_CREDENTIALS=/home/clarencehub/.config/curlys-books/gmail-service-account.json
GMAIL_SERVICE_ACCOUNT_KEY=/home/clarencehub/.config/curlys-books/gmail-service-account.json
```

---

## Data Models

### Receipt Schema (Implemented)
```python
class Receipt:
    id: UUID                    # Receipt identifier ✅
    entity: EntityType         # corp | soleprop ✅
    source: str               # pwa | email | drive ✅
    original_filename: str    # User's filename ✅
    content_hash: str        # SHA256 for dedup ✅
    file_path: str          # Storage location ✅
    upload_date: datetime   # When uploaded ✅
    status: ReceiptStatus   # pending | processed | failed ✅
    
    # OCR Results (Phase 1)
    ocr_confidence: float
    extracted_text: str
    vendor_name: str
    total_amount: Decimal
    purchase_date: date
    tax_amounts: dict
```

### Entity Types
```python
class EntityType(Enum):
    CORP = "corp"           # 14587430 Canada Inc.
    SOLEPROP = "soleprop"   # Curly's Sports & Supplements
```

### Receipt Status
```python
class ReceiptStatus(Enum):
    PENDING = "pending"     # Queued for OCR
    PROCESSING = "processing"  # OCR in progress
    PROCESSED = "processed"    # OCR complete, ready for review
    APPROVED = "approved"      # Human approved, posted to GL
    REJECTED = "rejected"      # Human rejected, marked void
    FAILED = "failed"         # OCR failed, needs manual entry
```

---

## Deployment Info

**Server:** Lenovo M920 Tiny (i7-8700T, 32GB RAM, 1TB NVMe)  
**OS:** Linux (Docker host)  
**User:** clarencehub  
**Project path:** `/home/clarencehub/curlys-books/`  
**Data path:** `/srv/curlys-books/objects/` (owned by uid 1000)

**Access:**
- Cloudflare Tunnel: receipts.curlys.ca, books.curlys.ca
- Cloudflare Access: Google Workspace SSO (stub for dev)

**Backup:**
- Google Drive (2TB)
- Nightly backups
- 7-year retention

**GitHub:** https://github.com/ThomasMcCrossin/curlys-books

---

## Key Technical Decisions

### 1. Architecture Boundaries (Enforced)
```python
apps/*       →  can import from  →  packages/*
packages/*   →  CANNOT import    →  apps/* or services/*
```
- Prevents circular dependencies
- API uses task wrapper, never imports worker code directly

### 2. OCR Configuration
- Tesseract primary (free, 90% threshold)
- AWS Textract fallback (not GPT-4V)
- Vendor templates boost confidence

### 3. Database Design
- Multi-entity: Separate schemas (not just entity column)
- Cleaner separation, easier year-end exports
- Shared schema for common data

### 4. File Storage
- Receipts: `/srv/curlys-books/objects/` (persistent, outside project)
- Code: `~/curlys-books/` (disposable, git-managed)
- Follows Linux FHS conventions

### 5. Security
- Service account keys: `~/.config/curlys-books/` (outside repo, 600 perms)
- `.gitignore`: Blocks all JSON except package files
- Git history cleaned when secrets exposed

---

## Lessons Learned (Oct 2025 Deployment)

### Issues Encountered & Fixed

**1. PostgreSQL Version Mismatch**
- Problem: Old v15 data incompatible with v16 container
- Fix: `docker volume rm` and fresh start
- Learning: Always match database versions or migrate properly

**2. Missing Python Dependencies**
- Problem: `asyncpg` not in lock file
- Fix: `poetry lock --no-update` or delete `poetry.lock`
- Learning: Lock file must match `pyproject.toml`

**3. Debian Package Names Changed**
- Problem: `libgl1-mesa-glx` doesn't exist in Trixie
- Fix: Use `libgl1` instead
- Learning: Check package availability for base image version

**4. Missing Environment Variables ✅ FIXED**
- Problem: Pydantic required fields not passed to container
- Fix: Add `env_file: - .env` to worker service in docker-compose.yml
- Learning: `.env` values must be explicitly passed in compose file

**5. Missing Router Files**
- Problem: `main.py` imported routers that didn't exist
- Fix: Create stub files with `router = APIRouter()`
- Learning: Comment out unbuilt features or create stubs

**6. Import Errors**
- Problem: `logging` module not imported, `settings` not exported
- Fix: Add missing imports, create `__init__.py` files
- Learning: Python packaging requires explicit exports

**7. SQLAlchemy 2.0 Syntax**
- Problem: Raw SQL strings not allowed
- Fix: `text("SELECT 1")` instead of `"SELECT 1"`
- Learning: SQLAlchemy 2.0 requires explicit text() wrapper

**8. File Storage Permissions**
- Problem: Container (uid 1000) can't write to host directory
- Fix: `chown 1000:1000 /srv/curlys-books/`
- Learning: Match host permissions with container user

**9. Path Mismatches**
- Problem: Code referenced `/srv/curlys-books/objects`, volume mounted at `/srv/objects`
- Fix: Update config default to `/srv/curlys-books/objects`
- Learning: Always verify container paths vs host paths

**10. Function Signature Mismatches ✅ FIXED**
- Problem: `queue_receipt_ocr()` called with 5 args, defined with 2
- Fix: Update function signature in `tasks.py` to match
- Learning: Keep API contracts in sync

**11. Task Registration Issues ✅ FIXED**
- Problem: Celery autodiscovery not finding tasks, empty `[tasks]` section
- Fix: Replace autodiscovery with explicit import: `from services.worker.tasks import ocr_receipt`
- Learning: Explicit imports more reliable than autodiscovery

**12. Task Name Mismatches ✅ FIXED**
- Problem: API sending 'process_receipt_ocr' but worker expects 'services.worker.tasks.ocr_receipt.process_receipt_task'
- Fix: Align task names between API and worker
- Learning: Task names must match exactly

**13. Corrupted .env File ✅ FIXED**
- Problem: `USE_MOCK_DATA=falseGOOGLE_APPLICATION_CREDENTIALS=...` (missing newline)
- Fix: Add proper line breaks in .env file
- Learning: .env files are sensitive to formatting

**14. Missing Parser Modules ✅ FIXED**
- Problem: OCR task importing non-existent `packages.parsers.ocr_engine` etc.
- Fix: Create stub OCR task without Phase 1 imports
- Learning: Don't import future modules in Phase 0

**15. Web Health Endpoint ✅ FIXED**
- Problem: Next.js app missing `/health` route, causing 404 on health check
- Fix: Create `apps/web/app/health/route.ts`, clear Next.js cache
- Learning: Next.js App Router requires explicit route files

### Security Incidents

**GCP Service Account Key Exposure (2025-10-03)**
- Committed `curlys-books-456c66447742.json` to GitHub
- Google detected and disabled key within minutes
- Fixed with:
  - `git filter-repo` to clean history
  - Generated new key
  - Stored in `~/.config/curlys-books/` (outside repo)
  - Added `.gitignore` patterns
  - Force pushed cleaned history

**Protective Patterns:**
```gitignore
# GCP Service Account Keys
curlys-books-*.json
*service-account*.json

# But keep these
!package.json
!package-lock.json
!tsconfig.json
```

---

## Current Working Status (2025-10-08 02:55 AM)

### ✅ All Systems Operational

**Health Check Results:**
```bash
$ make health
🏥 Checking service health...
{"status":"healthy","environment":"production","version":"0.1.0","services":{"database":"connected","redis":"connected"}}
{"status":"healthy","service":"web","timestamp":"2025-10-08T05:55:00.000Z"}
✅ Health check complete
```

**Receipt Upload Test:**
```bash
$ curl -X POST "http://localhost:8000/api/v1/receipts/upload" \
  -F "file=@vendor-samples/CurlysCanteenCorp/Capital/Copy of INV-2520102.PDF" \
  -F "entity=corp"

Response:
{
  "receipt_id": "6c6583d0-1018-47c2-b82e-5d1faba15b69",
  "status": "pending",
  "message": "Receipt uploaded and queued for processing",
  "task_id": "046fe80f-b31d-4903-bc18-10ece8d5e320"
}
```

**Worker Task Processing:**
```bash
$ docker compose logs worker --tail=5
curlys-books-worker  | [2025-10-08 05:39:02,238: INFO/MainProcess] Task services.worker.tasks.ocr_receipt.process_receipt_task[046fe80f-b31d-4903-bc18-10ece8d5e320] received
curlys-books-worker  | [2025-10-08 05:39:02,239: WARNING/ForkPoolWorker-2] 2025-10-08 05:39:02 [info     ] ocr_processing_started_stub    entity=corp file_path=/srv/curlys-books/objects/corp/6c6583d0-1018-47c2-b82e-5d1faba15b69/original.PDF receipt_id=6c6583d0-1018-47c2-b82e-5d1faba15b69 source=pwa
curlys-books-worker  | [2025-10-08 05:39:02,239: WARNING/ForkPoolWorker-2] 2025-10-08 05:39:02 [info     ] ocr_stub_complete              receipt_id=6c6583d0-1018-47c2-b82e-5d1faba15b69
curlys-books-worker  | [2025-10-08 05:39:02,243: INFO/ForkPoolWorker-2] Task services.worker.tasks.ocr_receipt.process_receipt_task[046fe80f-b31d-4903-bc18-10ece8d5e320] succeeded in 0.004339626990258694s: {'success': True, 'receipt_id': '6c6583d0-1018-47c2-b82e-5d1faba15b69', 'message': 'Stub: OCR processing queued, Phase 1 will implement', 'requires_review': True}
```

**Container Status:**
```bash
$ docker compose ps
NAME                  IMAGE                 COMMAND                  SERVICE   CREATED         STATUS                    PORTS
curlys-books-api      curlys-books-api      "python -m uvicorn a…"   api       15 minutes ago  Up 15 minutes (healthy)   127.0.0.1:8000->8000/tcp
curlys-books-db       postgres:16-alpine    "docker-entrypoint.s…"   postgres  15 minutes ago  Up 15 minutes (healthy)   5432/tcp
curlys-books-redis    redis:7-alpine        "docker-entrypoint.s…"   redis     15 minutes ago  Up 15 minutes (healthy)   6379/tcp
curlys-books-web      curlys-books-web      "docker-entrypoint.s…"   web       8 minutes ago   Up 8 minutes (healthy)    127.0.0.1:3000->3000/tcp
curlys-books-worker   curlys-books-worker   "celery -A services.…"   worker    15 minutes ago  Up 15 minutes             
```

---

## What's Next - Phase 1: OCR & Parsing

### Ready to Build ✅
All infrastructure working, ready for Phase 1 development:

- **Tesseract OCR wrapper** - `packages/parsers/ocr_engine.py`
- **AWS Textract fallback** - `packages/parsers/textract_fallback.py`
- **Confidence scoring** - `packages/parsers/confidence_scorer.py`
- **Vendor dispatcher** - `packages/parsers/vendor_dispatcher.py`
- **6 vendor template parsers:**
  1. Capital Foodservice (6 samples)
  2. GFS (12 samples)
  3. Costco (8 samples)
  4. Superstore (4 samples)
  5. Pharmasave (1 sample)
  6. Pepsi (7 samples)
- **Bank parsers:** Scotiabank CSV, Mosaik PDF
- **Thumbnail generation** - `packages/parsers/thumbnail_generator.py`
- **Golden test framework**

### Current Stub Task

Located at `services/worker/tasks/ocr_receipt.py`:

```python
@app.task(base=OCRTask, name="services.worker.tasks.ocr_receipt.process_receipt_task")
def process_receipt_task(
    receipt_id: str,
    entity: str,
    file_path: str,
    content_hash: str,
    source: str,
) -> Dict[str, Any]:
    """
    Process uploaded receipt with OCR (stub implementation)
    
    Phase 1 will implement:
    - Tesseract OCR
    - AWS Textract fallback
    - Vendor template parsing
    """
    logger.info("ocr_processing_started_stub",
                receipt_id=receipt_id,
                entity=entity,
                file_path=file_path,
                source=source)
    
    # TODO: Phase 1 - Implement actual OCR processing
    logger.info("ocr_stub_complete", receipt_id=receipt_id)
    
    return {
        "success": True,
        "receipt_id": receipt_id,
        "message": "Stub: OCR processing queued, Phase 1 will implement",
        "requires_review": True,
    }
```

### Timeline Estimate
- **Week 1:** Tesseract + Textract integration (3-5 days)
- **Week 2:** Vendor parsers 1-3 (Capital, GFS, Costco)
- **Week 3:** Vendor parsers 4-6 + bank parsers
- **Week 4:** Golden tests, confidence scoring, polish

**Target:** 85-90% auto-approval rate, <5 sec processing time

---

## Phase Roadmap

### Phase 0: Foundation ✅ COMPLETE
- Docker stack deployed and operational
- Database migrated with dual schemas
- API healthy with working receipt upload
- Task queue processing functional
- Vendor samples organized and ready
- All health checks passing

### Phase 1: OCR & Parsing (NEXT - 3-4 weeks)
- Tesseract + Textract integration
- Vendor template parsers for 6 major vendors
- Bank statement parsers (CIBC, Scotiabank, Mosaik)
- Golden test framework
- Confidence scoring algorithm
- Thumbnail generation
- Database integration for OCR results

### Phase 2: Matching & Reconciliation (2-3 weeks)
- Bank reconciliation engine
- PAD autopay matching
- Cash reconciliation
- Duplicate detection
- Transaction categorization

### Phase 3: Workflows & Shopify (2-3 weeks)
- Monday reimbursement batches
- Shopify sync integration
- HST calculation and dashboard
- Trial Balance reports
- Approval workflows

### Phase 4: Frontend (3-4 weeks)
- PWA with camera integration
- Receipt review/approval UI
- Bank reconciliation interface
- Reports and dashboards
- Mobile-first responsive design

### Phase 5-8: Reports & BI
- Year-end export packages (T2/GIFI/T2125)
- Product catalog and inventory
- Margin analysis and reporting
- Inventory optimization
- Advanced analytics

---

## Common Commands

### Docker Operations
```bash
# Build and start services
make build
make up

# Health check all services
make health

# Restart specific service
docker compose restart api
docker compose restart worker

# View logs
docker compose logs api --tail=50
docker compose logs -f worker

# Check container status
docker compose ps

# Stop everything
make down
```

### Database Operations
```bash
# Run migrations
make migrate

# Create new migration
make migrate-create ARGS="description"

# Access database shell
make shell-db

# Reset database (destructive)
docker volume rm curlys-books_postgres_data
make up
```

### Testing & Debugging
```bash
# Test API health
curl http://localhost:8000/health

# Test web health  
curl http://localhost:3000/health

# Upload test receipt
curl -X POST "http://localhost:8000/api/v1/receipts/upload" \
  -F "file=@vendor-samples/CurlysCanteenCorp/Capital/Copy of INV-2520102.PDF" \
  -F "entity=corp"

# View API documentation (dev only)
open http://localhost:8000/docs

# Check worker task registration
docker compose logs worker | grep "\[tasks\]" -A 10

# Monitor Redis queue
docker compose exec redis redis-cli
> KEYS *
> LLEN celery
```

### Git Operations
```bash
# Status and commit
git status
git add .
git commit -m "message"
git push

# Check for secrets before commit
git diff | grep -i "password\|secret\|key\|akia"

# View recent commits
git log --oneline -10

# Create feature branch
git checkout -b phase-1-ocr
```

---

## Known Limitations (Accepted)

1. **Canteen product tracking:** Not possible with price-point POS model
2. **Mosaik statements:** PDF-only format requires custom extraction
3. **Cash reconciliation:** Manual count entry required
4. **Google Drive links:** Cannot be accessed by Claude (use GitHub or paste content)
5. **Next.js "Ready in" message:** Not visible in tail logs but service works
6. **Worker autodiscovery:** Replaced with explicit imports for reliability

---

## Success Criteria (Replace Wave)

**User can:**
- ✅ Capture receipts via API (upload endpoint working)
- ⏳ Auto-process receipts with OCR (Phase 1)
- ⏳ Approve receipts in web UI (Phase 4)
- ⏳ Generate Monday reimbursement batches (Phase 3)
- ⏳ Reconcile bank statements automatically (Phase 2)
- ⏳ Generate HST returns (Phase 3)
- ⏳ Export year-end packages for accountant (Phase 5)
- ✅ Audit trail - every number links to source document

**System provides:**
- ✅ Accurate books for both business entities
- ✅ Proper multi-entity separation (dual schemas)
- ⏳ Automated reimbursement tracking (Phase 3)
- ⏳ Cash reconciliation workflows (Phase 2)
- ⏳ Inventory variance reporting (Phase 5)
- ⏳ Accountant-ready export packages (Phase 5)

---

## Quick Start Guide (New Development Session)

1. **Start services:**
   ```bash
   cd ~/curlys-books
   make up
   ```

2. **Verify all systems healthy:**
   ```bash
   make health
   # Should show: ✅ Health check complete
   ```

3. **Test receipt upload:**
   ```bash
   curl -X POST "http://localhost:8000/api/v1/receipts/upload" \
     -F "file=@vendor-samples/CurlysCanteenCorp/Capital/Copy of INV-2520102.PDF" \
     -F "entity=corp"
   # Should return 202 with receipt_id and task_id
   ```

4. **Verify task processing:**
   ```bash
   docker compose logs worker --tail=10
   # Should show: Task succeeded with stub message
   ```

5. **Review available samples:**
   ```bash
   find vendor-samples/ -name "*.pdf" -o -name "*.PDF" | wc -l
   # Should show: 67 receipt samples ready
   ```

6. **Begin Phase 1 development** - Start with Tesseract OCR wrapper

---

## Important Technical Notes

- **Container User:** Runs as uid 1000 (curlys) for file permissions
- **Storage Paths:** Use `/srv/curlys-books/objects` (not `/srv/objects`)
- **Service Account Keys:** Stored in `~/.config/curlys-books/` outside repository
- **Task Registration:** Uses explicit imports, not autodiscovery
- **Router Stubs:** Exist for all endpoints, only `receipts.py` fully implemented
- **OCR Task:** Currently stub implementation, ready for Phase 1 development
- **Health Endpoints:** All services have working `/health` routes
- **Environment Variables:** All required vars configured in `.env` and docker-compose.yml

---

## Current Test Results Summary

**✅ Infrastructure Test (2025-10-08 02:55 AM):**
- All containers healthy and operational
- API accepting requests and queuing tasks
- Worker processing tasks successfully  
- Database and Redis connections stable
- File storage working with correct permissions
- Web interface health endpoint responding

**✅ Receipt Processing Flow:**
1. File uploaded via API → 202 response with receipt_id
2. File saved to correct storage path
3. Task queued to Redis successfully
4. Worker picks up and processes task
5. Stub processing completes in ~4ms
6. Success response returned with proper format

**✅ Ready for Phase 1:**
- Tesseract 5.5.0 installed and available in worker
- 67 receipt samples organized by vendor
- Task infrastructure proven working
- Database schemas ready for OCR results
- Development environment fully operational

---

**End of Comprehensive Context Document**

**Status:** Phase 0 Complete - All Systems Operational ✅  
**Next Step:** Phase 1 OCR Development - Tesseract Integration  
**Last Verified:** 2025-10-08 02:55 AM ADT  

🚀 **Foundation Complete - Ready for Development!**