# Gmail Integration Setup Guide

This guide walks through setting up Gmail integration for email-based receipt capture using a Google Workspace service account.

---

## Why Service Account?

**Recommended approach:**
- ✅ No manual token refresh every 7 days
- ✅ Survives password changes
- ✅ Domain admin can revoke/audit centrally
- ✅ More stable than OAuth for server applications

**vs OAuth (not recommended):**
- ❌ Tokens expire frequently
- ❌ Breaks when user changes password
- ❌ Requires manual re-authentication

---

## Prerequisites

- Google Workspace account (not personal Gmail)
- Admin access to Google Workspace Admin Console
- Access to Google Cloud Console

---

## Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Click **Select a project** → **New Project**
3. Project name: `Curlys Books`
4. Click **Create**

---

## Step 2: Enable Gmail API

1. In your new project, go to **APIs & Services** → **Library**
2. Search for "Gmail API"
3. Click **Gmail API**
4. Click **Enable**

---

## Step 3: Create Service Account

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **Service Account**
3. Fill in details:
   - **Service account name:** `curlys-books-gmail`
   - **Service account ID:** `curlys-books-gmail` (auto-filled)
   - **Description:** "Service account for Curly's Books receipt email import"
4. Click **Create and Continue**
5. **Grant this service account access to project:** Skip (click Continue)
6. **Grant users access to this service account:** Skip (click Done)

---

## Step 4: Create Service Account Key

1. Find your newly created service account in the list
2. Click on it to open details
3. Go to **Keys** tab
4. Click **Add Key** → **Create new key**
5. Choose **JSON** format
6. Click **Create**
7. A JSON file will download automatically (e.g., `curlys-books-gmail-a1b2c3d4e5f6.json`)

**⚠️ Important:** Keep this file secure! Anyone with this file can access Gmail as this service account.

---

## Step 5: Enable Domain-Wide Delegation

1. In the service account details, find **Advanced settings** section
2. Copy the **Client ID** (long number like `123456789012345678901`)
3. Check the box **Enable Google Workspace Domain-wide Delegation**
4. Click **Save**

---

## Step 6: Grant Domain-Wide Delegation in Workspace Admin

1. Go to [Google Workspace Admin Console](https://admin.google.com)
2. Navigate to **Security** → **Access and data control** → **API Controls**
3. Scroll to **Domain-wide delegation**
4. Click **Manage Domain Wide Delegation**
5. Click **Add new**
6. Fill in:
   - **Client ID:** Paste the Client ID from Step 5
   - **OAuth Scopes:** Enter these scopes (comma-separated):
     ```
     https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.modify
     ```
7. Click **Authorize**

---

## Step 7: Configure Email Addresses

### Option A: Use Your Existing Email (Recommended - FREE)

Use your existing Workspace email - no new user needed:

**Setup:**
1. Service account will impersonate: `tom@curlys.ca`
2. Create Gmail labels:
   - `Receipts/Inbox` (all incoming receipts)
   - `Receipts/Corp` (for Canteen)
   - `Receipts/SoleProp` (for Sports)
   - `Receipts/Imported` (processed receipts)

3. Create Gmail filters for auto-labeling:
   - **Filter 1:** Subject contains `[Canteen]` → Apply label `Receipts/Corp`
   - **Filter 2:** Subject contains `[Sports]` → Apply label `Receipts/SoleProp`
   - **Filter 3:** From contains `invoice@` → Apply label `Receipts/Inbox`

4. When forwarding receipts, add subject prefix:
   - `[Canteen] Costco receipt` → Auto-labels as Corp
   - `[Sports] GNC invoice` → Auto-labels as SoleProp

**Cost: $0/month**

### Option B: Use Plus Addressing (Also FREE)

Gmail supports + addressing on your existing email:

1. Forward receipts to:
   - `tom+corp@curlys.ca` → Routes to you, system detects Corp
   - `tom+sp@curlys.ca` → Routes to you, system detects SoleProp

2. Service account impersonates: `tom@curlys.ca`
3. System reads all mail, routes by address

**Cost: $0/month**

### Option C: Google Groups (FREE)

Create email aliases without new users:

1. Admin Console → **Groups** → **Create Group**
2. Create groups:
   - `receipts-corp@curlys.ca` → Add tom@curlys.ca as member
   - `receipts-sports@curlys.ca` → Add tom@curlys.ca as member
3. Emails to groups forward to you automatically

**Cost: $0/month**

### Option D: Dedicated Mailbox (NOT Recommended - COSTS $6-12/month)

Only use if you have unused Workspace licenses:

1. In Google Workspace Admin, go to **Users**
2. Click **Add new user**
3. Create user:
   - Email: `receipts@curlys.ca`
   - Name: `Receipts Bot`
4. Click **Add user**

**Cost: $6-12/month depending on Workspace plan**

**Why not recommended:** Unnecessary cost when free options work equally well.

---

## Step 8: Transfer Service Account Key to Server

1. Copy the downloaded JSON file to your server:
   ```bash
   scp curlys-books-gmail-*.json user@your-server:/srv/curlys-books/
   ```

2. Secure the file:
   ```bash
   ssh user@your-server
   cd /srv/curlys-books
   chmod 600 curlys-books-gmail-*.json
   chown $USER:$USER curlys-books-gmail-*.json
   ```

---

## Step 9: Configure Environment Variables

Edit your `.env` file:

```bash
nano ~/curlys-books/.env
```

Add these lines:

```bash
# Gmail Service Account
GMAIL_SERVICE_ACCOUNT_JSON=/srv/curlys-books/curlys-books-gmail-XXXXX.json
GMAIL_IMPERSONATE_EMAIL=receipts@curlys.ca

# Receipt routing addresses
GMAIL_CORP_ADDRESS=receipts+corp@curlys.ca
GMAIL_SOLEPROP_ADDRESS=receipts+sp@curlys.ca
```

Replace:
- `curlys-books-gmail-XXXXX.json` with your actual filename
- `receipts@curlys.ca` with your mailbox

---

## Step 10: Test the Integration

1. Restart the worker service:
   ```bash
   cd ~/curlys-books
   docker compose restart worker
   ```

2. Check logs:
   ```bash
   make logs ARGS="worker"
   ```

3. Send a test email:
   - To: `receipts+corp@curlys.ca`
   - Subject: "Test receipt"
   - Attach: A sample receipt PDF or image

4. Watch logs for processing:
   ```bash
   make logs ARGS="-f worker"
   ```

You should see:
```
gmail_check_started mailbox=receipts@curlys.ca
new_message_found message_id=... has_attachments=true
receipt_queued_from_email entity=corp
```

---

## Troubleshooting

### Error: "Service account not authorized"

**Cause:** Domain-wide delegation not properly configured

**Fix:**
1. Verify Client ID matches in Admin Console
2. Check OAuth scopes are correct
3. Wait 10-15 minutes for changes to propagate

### Error: "User not found" or "Mailbox does not exist"

**Cause:** Impersonation email doesn't exist or typo

**Fix:**
1. Verify `GMAIL_IMPERSONATE_EMAIL` matches actual mailbox
2. Check mailbox exists in Workspace Admin
3. No typos in email address

### Error: "Permission denied" reading service account file

**Cause:** File permissions too restrictive or wrong path

**Fix:**
```bash
ls -la /srv/curlys-books/*.json
chmod 600 /srv/curlys-books/curlys-books-gmail-*.json
```

### No emails being processed

**Check:**
1. Are emails actually arriving in the mailbox?
2. Is the worker service running? `docker ps`
3. Are there errors in logs? `make logs ARGS="worker"`
4. Is the scheduled job running? Check Celery beat logs

---

## Email Processing Logic

### How It Works:

1. **Scheduled Check:** Every 15 minutes, Celery worker checks Gmail
2. **Label Filter:** Only reads messages labeled `Receipts/Inbox` or similar
3. **Process Attachments:**
   - PDF, JPG, PNG, HEIC files extracted
   - HTML-only emails rendered to PDF
4. **Entity Routing:**
   - Email to `receipts+corp@` → Corp entity
   - Email to `receipts+sp@` → Sole Prop entity
   - Default: Corp (if no routing suffix)
5. **Mark Processed:** Moves to `Receipts/Imported` label
6. **Queue OCR:** Each attachment queued for processing

---

## Security Best Practices

### File Security
```bash
# Service account key should be:
-rw------- (600) owner:group /srv/curlys-books/gmail-sa.json
```

### Never Commit
Add to `.gitignore`:
```
*.json
service-account*.json
*-credentials.json
```

### Rotate Keys Annually
1. Create new service account key
2. Update `.env` with new path
3. Restart services
4. Delete old key from Google Cloud Console

### Monitor Access
- Check Google Workspace Admin → **Reporting** → **Audit and investigation** → **Gmail log events**
- Review service account activity monthly

---

## Alternative: OAuth Setup (Not Recommended)

If you must use OAuth instead of service account:

1. Create OAuth 2.0 credentials in Google Cloud Console
2. Configure consent screen
3. Download client secrets
4. Run OAuth flow to get refresh token:
   ```bash
   python scripts/gmail_oauth_setup.py
   ```
5. Store tokens in `.env`:
   ```bash
   GMAIL_CLIENT_ID=your-client-id
   GMAIL_CLIENT_SECRET=your-client-secret
   GMAIL_REFRESH_TOKEN=your-refresh-token
   ```

**Downsides:**
- Tokens expire every 7 days (requires re-auth)
- Breaks when user changes password
- More maintenance overhead

**We won't build this unless service account doesn't work for your use case.**

---

## Summary Checklist

- [ ] Google Cloud project created
- [ ] Gmail API enabled
- [ ] Service account created
- [ ] Service account key downloaded (JSON)
- [ ] Domain-wide delegation enabled
- [ ] Scopes authorized in Workspace Admin
- [ ] Mailbox created (`receipts@curlys.ca`)
- [ ] Email aliases configured (`+corp`, `+sp`)
- [ ] JSON file transferred to server
- [ ] File permissions secured (600)
- [ ] `.env` configured with paths
- [ ] Worker service restarted
- [ ] Test email sent and processed
- [ ] Logs confirm successful processing

---

**Need help?** Open an issue with logs from `make logs ARGS="worker"`