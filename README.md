Curly's Books
Multi-entity accounting system for 14587430 Canada Inc. (Curly's Canteen) and Sole Prop (Curly's Sports & Supplements).

Replaces Wave with accountant-grade books, HST returns, T2/GIFI, and T2125 exports. Dead-simple receipt capture from phone, email, or Drive.

🎯 Features
Receipt Capture
PWA Camera: Snap receipts from phone with auto-crop, deskew, and offline queue
Long Receipt Mode: Multi-segment capture for thermal receipts
Email-In: Forward receipts to receipts+corp@curlys.ca or receipts+sp@curlys.ca
Drive Sync: Watch folders sync automatically
Duplicate Detection: Content hash + perceptual hash prevents double-counting
Parsing & Classification
Hybrid OCR: Tesseract first, GPT-4V fallback for low confidence
Vendor Templates: Optimized for Capital, GFS, Costco, Superstore, Pharmasave, Wholesale Club
Smart Tax Engine: NS HST 14% (after 2025-04-01), 15% before, line-level ITC tracking
Auto-categorization: Maps vendor SKUs to GL accounts
Banking & Reconciliation
Statement Import: CIBC CSV/OFX/QFX, automatic merchant extraction
Match Engine: ±0.5%/$0.02 amount tolerance, -3/+5 day window
Owner-Paid Tracking: Due to/from Shareholder with reimbursement workflow
Personal/Business Split: Flag personal transactions with quick buttons
Bills & Autopay (PAD)
A/P Tracking: Separate bill workflow for Net terms vendors
PAD Reconciliation: Auto-match Capital (Net 7), GFS (Net 14), Pepsi (15th next month)
Exception Handling: Alerts for late/mismatched autopay transactions
Reimbursements (Corp Only)
Monday Batch: Auto-generate at 09:00, group by person + card
Approval Workflow: Review, uncheck outliers, generate payment checklist
Auto-clear: Bank imports match and clear Due to Shareholder
Shopify Integration
Dual Stores: Canteen (Corp) and Sports (Sole Prop)
Revenue Mapping: Product types/tags → GL accounts
Tender Clearing: Shopify Payments, terminals, cash, gift cards, tips
Payout Reconciliation: Fees, chargebacks, bank deposits
HST Summary: Collected tax reconciles to HST Payable
Year-End Exports
Corp: Trial Balance, GIFI CSV (Schedules 100/125), CCA/Schedule 8, HST return + GL reconciliation
Sole Prop: Trial Balance, T2125-ready pack, HST return + GL reconciliation
Audit Pack: Every journal entry links to source receipt PDF/JPG
🚀 Quick Start
Prerequisites
Docker and Docker Compose installed
Home Server: Lenovo M920 Tiny (i7-8700T, 32GB RAM, 1TB NVMe)
Cloudflare Tunnel: Already configured (ab0fcffa-7192-4ee6-a361-5198d144d708)
Storage:
/srv/curlys-books/objects for receipt storage
/library for organized receipt library
Google Drive 2TB for backups
Initial Setup
bash
# 1. Clone the repository
git clone https://github.com/ThomasMcCrossin/curlys-books.git
cd curlys-books

# 2. Create .env from example
cp .env.example .env
nano .env  # Fill in your credentials

# 3. Create storage directories
sudo mkdir -p /srv/curlys-books/objects
sudo mkdir -p /library/{curlys_corp,curlys_soleprop}/Receipts
sudo chown -R $USER:$USER /srv/curlys-books /library

# 4. Build and start services
make build
make up

# 5. Run database migrations
make migrate

# 6. Seed initial data (chart of accounts, vendors, GIFI mapping)
make seed

# 7. Check health
make health
Access the Application
Once running:

Web UI: https://receipts.curlys.ca (capture/review)
Reports: https://books.curlys.ca (financials/exports)
API Docs: https://books.curlys.ca/docs (Swagger)
All access protected by Cloudflare Access (Google Workspace SSO + 2FA).

📂 Project Structure
curlys-books/
├── apps/
│   ├── api/                    # FastAPI backend
│   │   ├── routers/
│   │   │   ├── receipts.py            # Receipt upload/review
│   │   │   ├── banking.py             # Statement import/reconciliation
│   │   │   ├── reimbursements.py      # Monday batch workflow
│   │   │   └── reports.py             # TB, HST, GIFI exports
│   │   └── middleware/
│   │       └── auth_cloudflare.py     # JWT validation
│   └── web/                    # Next.js PWA
│       ├── pages/
│       │   ├── capture.tsx            # Camera capture
│       │   ├── inbox.tsx              # Review queue
│       │   ├── bank-rec.tsx           # Reconciliation UI
│       │   └── reports/               # Financial reports
│       └── components/
│           ├── ReceiptPreview.tsx
│           └── LineItemEditor.tsx
│
├── services/
│   └── worker/                 # Celery background jobs
│       ├── celery_app.py
│       └── tasks/
│           ├── ocr_receipt.py         # Tesseract + GPT fallback
│           ├── parse_vendor.py        # Vendor-specific extraction
│           ├── match_banking.py       # Bank reconciliation
│           ├── sync_shopify.py        # Shopify API polling
│           ├── process_pad.py         # Autopay matching
│           └── backup_to_drive.py     # Nightly backup
│
├── packages/
│   ├── domain/                 # Pure business logic (no I/O)
│   │   ├── accounting/
│   │   │   ├── journal_entry.py
│   │   │   ├── posting_rules.py
│   │   │   ├── hst_calculator.py      # 15%→14% on 2025-04-01
│   │   │   └── cca_schedule.py        # Asset depreciation
│   │   └── validation/
│   │       ├── receipt_validator.py
│   │       └── matching_rules.py      # ±0.5%, -3/+5 days
│   │
│   ├── parsers/
│   │   ├── ocr_engine.py              # Tesseract wrapper
│   │   ├── statement_parser.py        # CIBC CSV parser
│   │   ├── layout_analyzer.py         # Bbox → table structure
│   │   └── vendor_dispatcher.py       # Route to correct template
│   │
│   ├── matching/
│   │   ├── bank_matcher.py            # Statement → receipt
│   │   ├── pad_matcher.py             # PAD → A/P bill
│   │   └── duplicate_detector.py      # Perceptual + content hash
│   │
│   └── common/
│       ├── schemas/                   # Pydantic models
│       │   ├── receipt_normalized.py
│       │   ├── posting_decision.py
│       │   └── journal_entry.py
│       └── errors.py                  # Custom exceptions
│
├── infra/
│   ├── docker/
│   │   ├── docker-compose.yml
│   │   └── postgres/init.sql
│   ├── db/
│   │   └── alembic/
│   │       └── versions/
│   │           └── 001_initial_schema.py
│   └── ops/
│       └── backup_restore.sh
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│       └── golden_receipts/           # Vendor samples with expected JSON
│           ├── capital/
│           ├── costco/
│           └── ...
│
├── docs/
│   ├── adr/                           # Architecture Decision Records
│   └── integrations/
│       ├── shopify.md
│       ├── gmail.md
│       └── cloudflare.md
│
├── Makefile                           # make up, make test, make migrate
├── .env.example
└── README.md
🔧 Common Tasks
Import Bank Statements
bash
# CIBC chequing (Canteen)
make import-csv ARGS="statements/canteen_202501.csv corp"

# CIBC chequing (Store)
make import-csv ARGS="statements/store_202501.csv soleprop"

# Credit cards
make import-csv ARGS="statements/visa_thomas.csv corp"
make import-csv ARGS="statements/mc_dwayne.csv corp"
Capture Receipts
From PWA:

Visit https://receipts.curlys.ca on your phone
Tap "Capture Receipt"
Select entity (Corp / Sole Prop)
Take photo (or multi-segment for long receipts)
Review parsed data, approve or fix
From Email:

Forward to receipts+corp@curlys.ca for Canteen
Forward to receipts+sp@curlys.ca for Sports
From Drive:

Drop in Drive/Receipts Inbox/Corp/ or Drive/Receipts Inbox/SoleProp/
Sync runs every 15 minutes
Monday Reimbursement Workflow
Automated batch preparation:

Runs every Monday at 09:00
Groups owner-paid receipts by person + card
Sends notification to review
Manual approval:

Visit https://books.curlys.ca/reimbursements
Review batch (e.g., "Thomas Visa ...0318 — $342.67")
Uncheck any outliers
Click "Approve" → generates Payment Checklist
Log into CIBC, send bill payments
Mark batch as "Paid" with payment date
Auto-reconciliation:

Bank import detects bill payment transactions
Matches by amount + payee + date window
Clears "Due to Shareholder" automatically
Generate Year-End Exports
bash
# Corp year-end (May 31)
make export-year-end ARGS="corp 2025"

# Sole prop year-end (Dec 31)
make export-year-end ARGS="soleprop 2024"
Exports include:

Trial Balance (PDF + CSV)
GIFI-mapped CSV (T2 Schedules 100/125)
CCA/Schedule 8 (asset register)
HST return with GL reconciliation
Audit pack (ZIP of all receipts + JEs)
🗄️ Database
Multi-Entity Separation
Two separate Postgres schemas:

curlys_corp — 14587430 Canada Inc. (Canteen)
curlys_soleprop — Curly's Sports & Supplements
shared — Users, feature flags, card registry, audit log
Immutable Audit Trail
Every mutation to receipts, bills, journal entries, and reimbursements triggers:

Audit log entry (who, when, what changed)
Updated timestamp (updated_at column)
Backups
Automated nightly:

bash
# Backup (triggered by cron)
make backup

# Restore from specific backup
make restore ARGS="2025-01-15_03-00"
Retention: 7 years (2,555 days) on Google Drive

🔐 Security
Access Control
Cloudflare Tunnel: No public ports, all traffic through tunnel
Cloudflare Access: Google Workspace SSO + 2FA required
Zero Trust: Only authenticated users from your Google Workspace can access
Secrets Management
Environment variables: Stored in .env (never committed)
GitHub Secrets: For CI/CD workflows
Encrypted at rest: Database backups encrypted before upload to Drive
PII Protection
Card numbers: Only last 4 digits stored
Masking: UI shows ****0318, never full PAN
Virus scanning: All uploads scanned before processing
🧪 Testing
Run Tests
bash
# All tests with coverage
make test

# Unit tests only (fast)
make test-unit

# Integration tests
make test-integration

# Golden receipt tests (vendor parsing)
make test-golden
Coverage Requirements
packages/domain: ≥85%
packages/parsers: ≥85%
services/worker: ≥85%
Golden Tests
Each priority vendor has 3-5 sample receipts with expected outputs:

ReceiptNormalized JSON
PostingDecision JSON
Final JournalEntry JSON
Located in tests/fixtures/golden_receipts/<vendor>/.

📊 Monitoring
Health Checks
bash
make health
Checks:

API health endpoint
Web health endpoint
Postgres pg_isready
Redis PING
Logs
bash
# All services
make logs

# Specific service
make logs ARGS="worker"

# Follow logs in real-time
make logs ARGS="-f api"
Metrics (Optional)
If METRICS_ENABLED=true:

Prometheus metrics: http://localhost:9090/metrics
Includes: parse latency, auto-post %, unmatched transactions, PAD variance
🛠️ Development
Pre-commit Hooks
bash
make pre-commit-install
Runs before each commit:

ruff (Python linting)
black (Python formatting)
isort (Python import sorting)
mypy (Python type checking)
eslint (TypeScript linting)
prettier (TypeScript formatting)
Create Migration
bash
make migrate-create ARGS="add_shopify_sync_timestamp"
Check Import Boundaries
bash
make check-imports
Enforces:

apps/* can import from packages/*
packages/* cannot import from apps/*
No circular dependencies
Open Shell
bash
# API container
make shell-api

# Worker container
make shell-worker

# PostgreSQL shell
make shell-db
📖 Documentation
Architecture Decision Records
Key decisions documented in docs/adr/:

001-ocr-strategy.md — Hybrid Tesseract + GPT-4V
002-entity-separation.md — Separate schemas vs entity column
003-reimbursement-flow.md — Monday batch workflow
004-pad-matching.md — Autopay reconciliation logic
Integration Guides
docs/integrations/shopify.md — Setting up Shopify API
docs/integrations/gmail.md — Service account vs OAuth
docs/integrations/cloudflare.md — Tunnel + Access setup
🐛 Troubleshooting
Services Won't Start
bash
# Check logs
make logs

# Rebuild images
make build

# Clean and restart
make clean
make up
Database Migration Failed
bash
# Rollback one migration
make migrate-down

# Check current migration
docker compose exec api alembic current

# Manually fix data, then retry
make migrate
OCR Failing
Check logs:

bash
make logs ARGS="worker"
Common issues:

Tesseract not installed: Check worker Dockerfile
GPT API key invalid: Verify OPENAI_API_KEY in .env
Low confidence: Receipts sent to review queue (not an error)
Bank Matching Not Working
Verify tolerances in .env:

MATCH_AMOUNT_TOLERANCE_PERCENT=0.5
MATCH_AMOUNT_TOLERANCE_DOLLARS=0.02
MATCH_DATE_WINDOW_BEFORE_DAYS=3
MATCH_DATE_WINDOW_AFTER_DAYS=5
Check merchant extraction:

bash
docker compose exec api python packages/parsers/statement_parser.py statements/test.csv
🤝 Contributing
Branch Strategy
main — protected, requires PR + passing CI
feature/* — short-lived feature branches
fix/* — bug fixes
docs/* — documentation only
Pull Request Requirements
All tests pass
Coverage thresholds met
Lint + typecheck clean
Import boundaries respected
Schema version bumped if DB changes
ADR updated for architecture changes
Docs updated for user-facing changes
Code Owners
CODEOWNERS file requires review from ThomasMcCrossin on:

/packages/**
/infra/**
/db/**
/apps/**
📝 License
Proprietary — © 2025 Thomas McCrossin / 14587430 Canada Inc.

💡 Support
Issues: https://github.com/ThomasMcCrossin/curlys-books/issues
Email: thomas@curlys.ca
Discord: (if we set one up for development discussion)

🗺️ Roadmap
Phase 1 (Current)
 Foundation (Docker, DB, CI/CD)
 CSV statement parser
 OCR pipeline with vendor templates
 Bank reconciliation engine
 Basic web UI
Phase 2
 Reimbursement workflow
 PAD autopay matching
 Shopify sync
 HST dashboard
Phase 3
 Year-end exports (GIFI, T2, T2125)
 CCA schedule
 Audit pack generation
Phase 4 (Nice-to-Have)
 CPA-005 EFT export
 Price history / margin insights
 Mobile app (native)
 Tailscale admin access
Built with ❤️ for Nova Scotia small businesses

