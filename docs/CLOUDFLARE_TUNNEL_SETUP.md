# Cloudflare Tunnel Setup - Quick Guide

**Status:** ✅ Docker config ready, needs token
**Purpose:** Access review UI from work securely

## Quick Setup (5 Minutes)

### Step 1: Get Your Tunnel Token

1. Go to: https://one.dash.cloudflare.com/
2. Navigate to: **Access** → **Tunnels**
3. Find your tunnel: `ab0fcffa-7192-4ee6-a361-5198d144d708`
4. Click **Configure** → Copy the token

### Step 2: Add Token to .env

```bash
# Add to .env file
echo "CLOUDFLARE_TUNNEL_TOKEN=your_token_here" >> .env
```

**⚠️ Important:** Don't commit this token to git!

### Step 3: Configure Tunnel Routes

In Cloudflare dashboard under your tunnel:

**Public Hostnames:**
```
books.curlys.ca     → http://web:3000
receipts.curlys.ca  → http://web:3000
api.curlys.ca       → http://api:8000  (optional)
```

**Settings:**
- Type: HTTP
- URL: Internal docker service name (web:3000)
- No TLS Verify: Off

### Step 4: Start Tunnel

```bash
docker compose up -d cloudflared
docker compose logs -f cloudflared
```

**Look for:**
```
INF Connection registered connIndex=0 location=YYZ
INF Tunnel is now connected
```

### Step 5: Configure Cloudflare Access (Optional but Recommended)

**Protect your review UI with Google SSO:**

1. Go to: **Access** → **Applications** → **Add an application**
2. Choose: **Self-hosted**
3. Configure:
   - Name: Curly's Books Review
   - Subdomain: books
   - Domain: curlys.ca
   - Path: /review

4. **Allow access:**
   - Email: thomas@curlys.ca (your Google Workspace)
   - Require: Email ends with @curlys.ca

5. **Save**

Now only you can access `https://books.curlys.ca/review` (with Google login + 2FA)

## Test It Works

```bash
# From your work computer (or phone)
curl https://books.curlys.ca

# Or open in browser:
https://books.curlys.ca/review
```

## Troubleshooting

### "Tunnel not found"
```bash
# Check tunnel status
docker compose logs cloudflared

# Restart tunnel
docker compose restart cloudflared
```

### "502 Bad Gateway"
**Cause:** Web container not reachable from tunnel

**Fix:**
```bash
# Check web is running
docker compose ps web

# Restart web
docker compose restart web
```

### "Access Denied"
**Cause:** Cloudflare Access policy blocking you

**Fix:**
- Check you're logged into correct Google account
- Verify Access policy allows your email
- Clear browser cookies for curlys.ca

## Current Configuration

**Tunnel ID:** `ab0fcffa-7192-4ee6-a361-5198d144d708`
**Domains:**
- books.curlys.ca (review UI)
- receipts.curlys.ca (receipt upload)

**Services:**
- Web UI: http://web:3000
- API: http://api:8000

## Security Features

✅ **Google Workspace SSO** - Only @curlys.ca emails
✅ **2FA Required** - Google's 2-factor auth
✅ **No VPN needed** - Works on any network
✅ **No ports exposed** - Everything through Cloudflare
✅ **Encrypted tunnel** - TLS end-to-end

## Access from Work

Once configured:

1. Open browser
2. Go to: https://books.curlys.ca/review
3. Sign in with Google (if not already)
4. Review receipts!

Works on:
- Work computer
- Phone
- Tablet
- Any device with internet

## Monthly Cost

**$0** - Cloudflare Tunnel is free for up to 50 users

## Next Steps After Setup

- [ ] Test access from work computer
- [ ] Test access from phone
- [ ] Configure Access policy if needed
- [ ] Add bookmark to `https://books.curlys.ca/review`

---

**Need help?** Check tunnel logs: `docker compose logs cloudflared`
