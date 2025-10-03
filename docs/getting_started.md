# Getting Started with Curly's Books

Complete setup guide for deploying Curly's Books on your home server.

---

## Prerequisites

**Hardware:**
- Lenovo M920 Tiny (i7-8700T, 32GB RAM, 1TB NVMe) ✓ You have this
- Stable internet connection ✓
- Google Drive 2TB storage ✓ You have this

**Software Needed:**
- Docker and Docker Compose
- Git
- SSH access to your server

**Accounts:**
- Cloudflare account with Tunnel configured ✓ You have this
- Google Workspace account (tom@curlys.ca) ✓ You have this
- AWS account (for Textract OCR fallback) - We'll set up
- GitHub account (for repository access)

---

## Step 1: Install Docker

SSH into your server:

```bash
ssh clarencehub@your-server
```

Install Docker:

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to docker group
sudo usermod -aG docker clarencehub

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Log out and back in for group to take effect
exit
```

SSH back in and verify:

```bash
docker --version
docker compose version
```

---

## Step 2: Create Storage Directories

```bash
# Receipt storage
sudo mkdir -p /srv/curlys-books/objects/curlys_corp
sudo mkdir -p /srv/curlys-books/objects/curlys_soleprop

# Receipt library (organized by date)
sudo mkdir -p /library/curlys_corp/Receipts/2024
sudo mkdir -p /library/curlys_corp/Receipts/2025
sudo mkdir -p /library/curlys_soleprop/Receipts/2024
sudo mkdir -p /library/curlys_soleprop/Receipts/2025

# Set ownership
sudo chown -R clarencehub:clarencehub /srv/curlys-books
sudo chown -R clarencehub:clarencehub /library

# Verify
ls -la /srv/curlys-books
ls -la /library
```

---

## Step 3: Clone Repository

```bash
cd /home/clarencehub
git clone https://github.com/ThomasMcCrossin/curlys-books.git
cd curlys-books
```

---

## Step 4: Configure Environment

Create your `.env` file:

```bash
cp .env.example .env
nano .env
```

**Fill in these REQUIRED values:**

```bash
# Database (generate strong password)
DB_PASSWORD=your_strong_password_here_min_20_chars

# Application secret (generate random string)
SECRET_KEY=your_random_secret_key_min_32_chars

# Cloudflare Access (get from Cloudflare dashboard)
CLOUDFLARE_ACCESS_AUD=your-app-aud-tag
CLOUDFLARE_TEAM_DOMAIN=your-team.cloudflareaccess.com
CLOUDFLARE_TUNNEL_ID=ab0fcffa-7192-4ee6-a361-5198d144d708

# Gmail (plus addressing - FREE)
GMAIL_IMPERSONATE_EMAIL=tom@curlys.ca
GMAIL_CORP_ADDRESS=tom+corp@curlys.ca
GMAIL_SOLEPROP_ADDRESS=tom+sp@curlys.ca
```

**Generate strong passwords:**

```bash
# For DB_PASSWORD
openssl rand -base64 32

# For SECRET_KEY
openssl rand -base64 48
```

Save and exit: `Ctrl+X`, then `Y`, then `Enter`

**Verify your .env:**

```bash
grep "DB_PASSWORD=" .env
grep "SECRET_KEY=" .env
# Should show your values (keep private!)
```

---

## Step 5: Build Docker Images

```bash
cd /home/clarencehub/curlys-books
make build
```

This will:
- Build API container (FastAPI)
- Build Worker container (Celery + Tesseract OCR)
- Build Web container (Next.js PWA)

Takes 5-10 minutes on first build. Get coffee.

---

## Step 6: Start Services

```bash
make up
```

This starts:
- PostgreSQL database
- Redis (job queue)
- API server (port 8000)
- Background worker
- Web frontend (port 3000)

Check status:

```bash
docker ps
```

Should see 5 containers running.

---

## Step 7: Initialize Database

Run migrations:

```bash
make migrate
```

This creates:
- Dual schemas (curlys_corp, curlys_soleprop)
- All tables (receipts, bills, bank_statements, etc.)
- Audit trail system

Seed initial data:

```bash
make seed
```

This loads:
- Chart of accounts (100+ accounts with GIFI codes)
- Card registry (Dwayne's cards, your cards)
- Default vendors
- Feature flags

Verify health:

```bash
make health
```

Expected output:
```
API healthy
Web healthy  
DB healthy
Redis healthy
```

---

## Step 8: Configure Cloudflare Access

Your tunnel is already configured. Now set up authentication:

**In Cloudflare Dashboard:**

1. Go to **Zero Trust** → **Access** → **Applications**
2. Click **Add an application** → **Self-hosted**
3. Fill in:
   - Name: `Curly's Books`
   - Session Duration: `24 hours`
   - Application Domain:
     - `receipts.curlys.ca`
     - `books.curlys.ca`

4. **Identity providers:**
   - Add Google Workspace
   - Require 2FA

5. **Access policies:**
   - Create rule: "Allow Google Workspace users"
   - Email domain: `curlys.ca`

6. **Copy Application Audience (AUD) Tag**
   - Go to application → Overview
   - Copy the AUD tag

7. **Update .env:**
   ```bash
   nano /home/clarencehub/curlys-books/.env
   ```
   Paste your AUD tag:
   ```bash
   CLOUDFLARE_ACCESS_AUD=paste-your-aud-here
   ```

8. **Restart API:**
   ```bash
   make restart
   ```

---

## Step 9: Test Basic Functionality

### Import Your First Bank Statement

```bash
# Upload one of your CSV files
make import-csv ARGS="/path/to/canteencibc2025sofar.csv corp"
```

Should see:
```
Statement parsed: 494 transactions
Lines imported successfully
```

### Access the Web Interface

Open browser:
- https://books.curlys.ca

You should:
1. Be redirected to Google Workspace login
2. Sign in with tom@curlys.ca
3. Complete 2FA
4. See Curly's Books dashboard

### Check Logs

```bash
# View all logs
make logs

# Follow worker logs
make logs ARGS="-f worker"

# View API logs
make logs ARGS="api"
```

---

## Step 10: Set Up AWS Textract (OCR Fallback)

**Cost: ~$0.27/year for your volume**

Follow the complete guide: `docs/integrations/aws-textract.md`

**Quick version:**

1. Create AWS account
2. Create IAM user: `curlys-books-textract`
3. Grant permission: `AmazonTextractFullAccess`
4. Save access keys
5. Update .env:
   ```bash
   AWS_ACCESS_KEY_ID=your-key
   AWS_SECRET_ACCESS_KEY=your-secret
   AWS_REGION=ca-central-1
   ```
6. Restart worker:
   ```bash
   docker compose restart worker
   ```

**Set cost alert:** $10/month (way more than you'll use)

---

## Step 11: Set Up Gmail Integration (Email-In Receipts)

**Cost: $0 (uses your existing email)**

Follow: `docs/integrations/gmail-setup.md`

**Quick version:**

1. Create Google Cloud project
2. Enable Gmail API
3. Create service account
4. Download JSON key
5. Enable domain-wide delegation
6. Authorize in Workspace Admin (scopes: gmail.readonly, gmail.modify)
7. Copy JSON to server:
   ```bash
   scp gmail-sa.json clarencehub@server:/srv/curlys-books/
   chmod 600 /srv/curlys-books/gmail-sa.json
   ```

8. Update .env:
   ```bash
   GMAIL_SERVICE_ACCOUNT_JSON=/srv/curlys-books/gmail-sa.json
   ```

9. Create Gmail filters (auto-archive receipts):
   - To `tom+corp@curlys.ca` → Skip inbox, label `Receipts/Corp`
   - To `tom+sp@curlys.ca` → Skip inbox, label `Receipts/SoleProp`

10. Restart worker:
    ```bash
    docker compose restart worker
    ```

**Test:** Forward a receipt to `tom+corp@curlys.ca`
- Should NOT appear in inbox
- Should have label `Receipts/Corp`
- Check logs: `make logs ARGS="-f worker"`

---

## Step 12: Import Historical Data

### Bank Statements

```bash
# Canteen (Corp)
make import-csv ARGS="/path/to/canteen_statements/*.csv corp"

# Sports Store (Sole Prop)
make import-csv ARGS="/path/to/store_statements/*.csv soleprop"

# Credit cards (map to Corp for reimbursement)
make import-csv ARGS="/path/to/visa_statements/*.csv corp"
make import-csv ARGS="/path/to/mc_statements/*.csv corp"

# Personal accounts (mixed business/personal)
make import-csv ARGS="/path/to/mosaik_statements.pdf corp"
make import-csv ARGS="/path/to/scotiabank_statements.csv corp"
```

### Check Import Results

Visit: https://books.curlys.ca/banking/statements

Should see all imported statements with transaction counts.

---

## Daily Usage

### Capture Receipts

**Option 1: Email**
- Forward to `tom+corp@curlys.ca` (Canteen)
- Forward to `tom+sp@curlys.ca` (Sports)
- Never hits your inbox (auto-archived)
- Processed within 15 minutes

**Option 2: PWA (Phase 4)**
- Visit receipts.curlys.ca on phone
- Tap camera icon
- Take photo
- Submit

**Option 3: Drive (Future)**
- Drop in `Drive/Receipts Inbox/Corp/` or `.../SoleProp/`

### Review Receipts

1. Go to https://receipts.curlys.ca/inbox
2. See low-confidence receipts needing review
3. Fix any parsing errors
4. Click "Approve" to post to GL

### Import Bank Statements

**Weekly or Monthly:**

```bash
# Download CSV from CIBC online banking
make import-csv ARGS="~/Downloads/statement.csv corp"
```

### Check System Health

```bash
make health
make stats  # See container resource usage
```

### View Logs

```bash
make logs ARGS="-f worker"  # Watch OCR processing
make logs ARGS="api"        # Check API errors
```

---

## Backup & Maintenance

### Manual Backup

```bash
make backup
```

Creates:
- Database dump
- Receipt files
- Uploads to Google Drive

### Restore from Backup

```bash
make restore ARGS="2025-01-15_03-00"
```

### Update System

```bash
cd /home/clarencehub/curlys-books
git pull
make build
make restart
make migrate  # If database changes
```

---

## Troubleshooting

### Services won't start

```bash
# Check logs
make logs

# Check Docker
docker ps -a

# Rebuild and restart
make clean
make build
make up
```

### Can't access URLs

1. **Check tunnel:**
   ```bash
   sudo systemctl status cloudflared
   ```

2. **Check DNS:** Cloudflare dashboard → DNS
   - receipts.curlys.ca → CNAME to tunnel
   - books.curlys.ca → CNAME to tunnel

3. **Check Access:** Cloudflare → Zero Trust → Access
   - Your email in allowed users

### Database connection errors

```bash
# Check PostgreSQL
docker compose exec postgres pg_isready

# Check password in .env
grep DB_PASSWORD .env

# Restart database
docker compose restart postgres
```

### OCR not working

```bash
# Check worker logs
make logs ARGS="worker"

# Verify Tesseract
docker compose exec worker tesseract --version

# Check AWS credentials
grep AWS_ .env
```

### Receipts not importing from email

1. **Check Gmail filters:**
   - Settings → Filters
   - Verify `tom+corp@curlys.ca` filter exists
   - Should skip inbox and apply label

2. **Check worker logs:**
   ```bash
   make logs ARGS="-f worker"
   ```

3. **Check service account:**
   ```bash
   ls -la /srv/curlys-books/gmail-sa.json
   # Should be -rw------- (600)
   ```

---

## Next Steps

### Phase 2: Vendor Parsing (Next)

Once foundation is working:
1. Gather vendor receipt samples
2. Start new conversation with PROJECT_CONTEXT.md
3. Build OCR templates for your vendors

### Phase 3: Bank Matching

- Auto-reconcile statements to receipts
- PAD autopay matching
- Cash reconciliation

### Phase 4: Workflows

- Monday reimbursement batches
- Shopify sync
- HST dashboard

### Phase 5: Year-End

- GIFI exports
- T2/T2125 packages
- CCA schedules

---

## File Locations

```
/home/clarencehub/curlys-books/        # Application code
/srv/curlys-books/objects/             # Original receipts
/library/                               # Organized receipt library
/srv/curlys-books/gmail-sa.json        # Gmail credentials
/home/clarencehub/curlys-books/.env    # Configuration (KEEP SECURE)
```

---

## Important Commands Reference

```bash
# Start/Stop
make up          # Start all services
make down        # Stop all services
make restart     # Restart all services

# Database
make migrate     # Run migrations
make seed        # Load initial data
make shell-db    # Open PostgreSQL shell

# Maintenance
make backup      # Backup database and files
make restore     # Restore from backup
make health      # Check all services
make stats       # Show resource usage

# Development
make logs        # View all logs
make test        # Run tests
make lint        # Check code quality

# Import
make import-csv ARGS="file.csv entity"  # Import bank statement
```

---

## Security Checklist

- [ ] .env file has 600 permissions (`chmod 600 .env`)
- [ ] Strong database password (20+ chars)
- [ ] Cloudflare Access configured (Google Workspace SSO)
- [ ] 2FA required for access
- [ ] No public ports open
- [ ] Gmail service account key secure (600 permissions)
- [ ] AWS keys in .env only (never committed)
- [ ] Backups running to Google Drive
- [ ] .gitignore excludes .env and *.json files

---

## Getting Help

**Check logs first:**
```bash
make logs > ~/debug.log
```

**Open GitHub issue** with:
- What you tried
- Error message
- Relevant logs
- Steps to reproduce

**Repository:** https://github.com/ThomasMcCrossin/curlys-books

---

## Success Criteria

You know it's working when:

- [ ] Can access https://books.curlys.ca (with Google login)
- [ ] Can access https://receipts.curlys.ca (with Google login)
- [ ] Imported bank statements show in UI
- [ ] Email to `tom+corp@curlys.ca` auto-archives
- [ ] Worker processes receipts (check logs)
- [ ] `make health` shows all services healthy
- [ ] Backups completing to Google Drive

---

**You're ready to replace Wave.**

Next: Gather vendor receipts, start Phase 2 for OCR templates.
