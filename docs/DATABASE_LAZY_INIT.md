# Database Lazy Initialization

**Status:** ✅ Implemented
**Date:** 2025-10-13

## Problem

Scripts using `asyncio.run()` would fail with:
```
RuntimeError: DatabaseSessionManager not initialized
```

This happened because:
1. FastAPI calls `sessionmanager.init()` during startup lifecycle
2. Standalone scripts have no startup lifecycle
3. Scripts would try to use `get_db_session()` before initialization

## Solution

Implemented **lazy initialization** that auto-initializes from `DATABASE_URL` when first accessed.

### Changes Made

**File:** `packages/common/database.py`

1. **Made `init()` async** - Now uses `async with self._init_lock` for thread-safe initialization
2. **Added `initialized` property** - Check if sessionmanager is ready
3. **Added `_ensure_initialized()`** - Auto-init from environment on first use
4. **Modified `get_db_session()`** - Calls `_ensure_initialized()` before returning session

**File:** `apps/api/main.py`

- Changed `sessionmanager.init()` → `await sessionmanager.init()` (now async)

## How It Works

### In FastAPI (Explicit Init)
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Explicit initialization during startup
    await sessionmanager.init(settings.database_url)
    yield
    await sessionmanager.close()
```

### In Standalone Scripts (Lazy Init)
```python
import asyncio
from packages.common.database import get_db_session

async def my_script():
    # No init() needed - auto-initializes from DATABASE_URL
    async for session in get_db_session():
        # Use session...
        break

asyncio.run(my_script())
```

## Configuration

### Enable Lazy Init (Default)
```bash
DB_LAZY_INIT=1  # or "true" or "True" (default)
DATABASE_URL=postgresql://user:pass@localhost/db
```

### Disable Lazy Init (Production Strictness)
```bash
DB_LAZY_INIT=0  # Force explicit initialization
```

When disabled, scripts must call `await sessionmanager.init()` explicitly.

### SQL Query Logging
```bash
SQL_ECHO=1  # Log all SQL queries (default: 0)
```

## Benefits

✅ **Scripts work without boilerplate** - No need to copy/paste init code
✅ **FastAPI unchanged** - Still uses explicit init during startup
✅ **Thread-safe** - Double-checked locking prevents race conditions
✅ **Production control** - Can disable lazy init with `DB_LAZY_INIT=0`
✅ **Environment-based** - Reads `DATABASE_URL` automatically

## Testing

### Test Lazy Init
```bash
docker compose exec worker python -c "
import asyncio
from packages.common.database import get_db_session

async def test():
    async for session in get_db_session():
        print('✅ Lazy init worked!')
        break

asyncio.run(test())
"
```

### Test Script
```bash
docker compose exec worker python scripts/test_ocr_providers_simple.py
# Should work without initialization errors
```

## Architecture

### Before (Manual Init Required)
```
Script starts
    ↓
asyncio.run(main())
    ↓
get_db_session() → ❌ RuntimeError: Not initialized
```

### After (Lazy Init)
```
Script starts
    ↓
asyncio.run(main())
    ↓
get_db_session()
    ↓
_ensure_initialized() checks if initialized
    ↓ (not initialized)
Reads DATABASE_URL from environment
    ↓
await sessionmanager.init(DATABASE_URL)
    ↓
Returns session → ✅ Works!
```

## Double-Checked Locking

Prevents race conditions when multiple coroutines request sessions simultaneously:

```python
async def _ensure_initialized():
    if sessionmanager.initialized:  # 1st check (fast path)
        return

    async with _lazy_lock:          # Acquire lock
        if sessionmanager.initialized:  # 2nd check (inside lock)
            return
        # Only first coroutine initializes
        await sessionmanager.init(database_url)
```

## Migration Guide

### Old Script Pattern (No Longer Needed)
```python
# ❌ Old way - manual initialization
import os
from packages.common.database import sessionmanager, get_db_session

async def main():
    # Had to manually initialize
    sessionmanager.init(os.getenv("DATABASE_URL"))

    async for session in get_db_session():
        # Use session...
        pass

asyncio.run(main())
```

### New Script Pattern (Automatic)
```python
# ✅ New way - automatic lazy init
from packages.common.database import get_db_session

async def main():
    # No initialization needed!
    async for session in get_db_session():
        # Use session...
        pass

asyncio.run(main())
```

## Common Issues

### "DATABASE_URL not set"
**Cause:** Environment variable not available to script

**Solution:**
```bash
# Check environment
docker compose exec worker env | grep DATABASE_URL

# Or set explicitly in docker-compose.yml
```

### "DB lazy init disabled"
**Cause:** `DB_LAZY_INIT=0` or `DB_LAZY_INIT=false`

**Solution:**
```bash
# Enable lazy init
export DB_LAZY_INIT=1

# Or initialize explicitly in script
await sessionmanager.init(os.getenv("DATABASE_URL"))
```

### "Already initialized" warnings
**Cause:** Script calls `init()` explicitly after lazy init already ran

**Solution:** Remove manual `init()` calls - let lazy init handle it

## Related Files

- `packages/common/database.py` - Session manager with lazy init
- `apps/api/main.py` - FastAPI startup with explicit init
- `scripts/test_ocr_providers_simple.py` - Example script using lazy init

## Future Enhancements

- [ ] Add connection pool monitoring
- [ ] Add metrics for lazy init vs explicit init
- [ ] Support multiple database connections
- [ ] Add connection retry logic
