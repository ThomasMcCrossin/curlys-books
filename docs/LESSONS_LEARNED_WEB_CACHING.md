# Lessons Learned: Web Container Caching Issues

**Date:** 2025-10-11
**Context:** Implementing normalized receipt images in review UI

## The Problem

Changed the UI code to use `?file_type=normalized` query parameter, but the browser kept receiving the old version without any query parameter at all. The image remained full size (3072px) instead of the normalized size (800px).

## Root Cause

The web container uses a **Docker volume for Next.js cache** (`web_cache:/app/.next`). This cache persists between container restarts and even rebuilds.

### What DOESN'T Clear the Cache:

1. ❌ `docker compose restart web` - Just restarts the container
2. ❌ `docker compose up -d --build web` - Rebuilds image but keeps volumes
3. ❌ `docker compose stop && docker compose up -d` - Keeps volumes
4. ❌ Hard browser refresh (Ctrl+Shift+R) - Server is still serving cached version
5. ❌ Incognito mode - Server-side cache is the problem, not browser cache

### What DOES Clear the Cache:

✅ `docker volume rm curlys-books_web_cache`

**Full command sequence:**
```bash
docker compose down web
docker volume rm curlys-books_web_cache
docker compose up -d web
```

## Why This Happened

1. **Next.js production mode** - The web container runs `NODE_ENV=production` which heavily caches built pages
2. **Volume persistence** - Docker volumes persist data between container lifecycles by design
3. **Assumption error** - Assumed `--build` flag would clear all caches, but it only rebuilds the image, not volumes

## Additional Issues Encountered

### Issue #1: Query Parameter Not Being Read by FastAPI

**Symptom:** API always defaulting to `file_type="original"` even when `?type=normalized` was in URL

**Root Cause:** FastAPI parameter name mismatch
- Function parameter: `file_type: str = "original"`
- URL parameter being sent: `?type=normalized`
- FastAPI needs exact name match OR explicit `Query()` declaration

**Fix:**
```python
# WRONG - parameter name doesn't match URL
async def get_receipt_file(
    receipt_id: str,
    file_type: str = "original",
    ...
)

# CORRECT - use Query() to explicitly declare query parameter
from fastapi import Query

async def get_receipt_file(
    receipt_id: str,
    file_type: str = Query("original", description="..."),
    ...
)
```

**Lesson:** Always use `Query()` for query parameters in FastAPI to avoid silent defaults.

### Issue #2: Code Changes Not Reflected After Restart

**Symptom:** Added logging to API code, rebuilt container, but logging never appeared

**Root Cause:** Used `docker compose restart` instead of rebuild

**Lesson:**
- `docker compose restart` = reload running container (good for config changes)
- `docker compose up -d --build` = rebuild image from code (needed for code changes)

## Critical Lesson: Ask User for Browser DevTools Info Early

### What Went Wrong

Spent 60+ minutes debugging server-side when the issue was actually visible in the browser Network tab within 30 seconds.

**The browser showed immediately:**
- Request URL had NO query parameter at all
- Server was sending `filename="...original.jpg"`
- Content-Length showed full-size image (1.2MB not 145KB)

### New Protocol for Frontend Issues

**ALWAYS ask user to check Browser DevTools FIRST before server-side debugging:**

1. **Open DevTools:** F12 or Right-click → Inspect
2. **Network Tab:** Clear, then reload page
3. **Find the request:** Look for the problematic resource (image, API call, etc.)
4. **Share these details:**
   - Request URL (full URL with query params)
   - Request Method (GET, POST, etc.)
   - Status Code (200, 404, 500, etc.)
   - Response Headers (content-type, content-length, content-disposition)
   - Request Headers (if relevant)

**This takes 30 seconds and saves hours of blind debugging.**

### Example Request

Instead of guessing, user provided:
```
Request URL: http://192.168.2.20:8000/api/v1/receipts/.../file
                                      ↑ NO QUERY PARAMETER!
content-disposition: attachment; filename="..._original.jpg"
                                            ↑ WRONG FILE TYPE!
content-length: 1193060
                ↑ 1.2MB (should be 145KB)
```

This immediately revealed:
- ✅ Web container not sending query parameter → cache issue
- ✅ API defaulting to "original" → confirms web cache
- ✅ File size wrong → confirms it's serving wrong file

**Lesson:** The browser DevTools is the source of truth. Ask for it early and often for frontend issues.

## Prevention Checklist

When making web UI changes:

- [ ] **ASK USER FOR DEVTOOLS INFO FIRST** (Network tab, Console errors)
- [ ] Check if code change affects built assets (pages, components)
- [ ] If yes, clear web cache: `docker volume rm curlys-books_web_cache`
- [ ] Rebuild web container: `docker compose up -d --build web`
- [ ] Wait for "Ready" message in logs before testing
- [ ] Test in incognito to avoid browser cache confusion
- [ ] **ASK USER TO VERIFY IN DEVTOOLS** (confirm URL, status, size)

## Quick Reference Commands

```bash
# Full clean rebuild of web container
docker compose down web
docker volume rm curlys-books_web_cache
docker compose up -d --build web

# Check if web is ready
docker compose logs web --tail=10

# Verify container is running new code (check file in container)
docker compose exec web cat app/review/page.tsx | grep "YOUR_SEARCH_TERM"
```

## Cost Impact

This debugging session took approximately 60 minutes and involved:
- Multiple unnecessary container rebuilds
- Extended troubleshooting time
- User frustration

**Estimated cost:** ~$15-20 in API usage and development time

**Prevention cost:** 2 minutes to clear cache upfront + 30 seconds asking for DevTools = $0.50

**Lesson:** When in doubt, clear the cache AND ask for browser DevTools. It's faster than debugging blind.

## Related Documentation

- Docker volumes: https://docs.docker.com/storage/volumes/
- Next.js caching: https://nextjs.org/docs/app/building-your-application/caching
- FastAPI query parameters: https://fastapi.tiangolo.com/tutorial/query-params/
- Chrome DevTools Network: https://developer.chrome.com/docs/devtools/network/
