# OCR Provider Architecture

**Status:** ✅ Complete (Phase 1.5)
**Last Updated:** 2025-10-13

## Overview

The OCR system has been refactored to use a **provider pattern** with pluggable backends. This makes Tesseract optional and allows easy switching between OCR providers via configuration.

## Architecture

### Provider Interface

All OCR providers implement the `OcrProvider` protocol:

```python
from packages.parsers.ocr import extract_text_from_receipt

result = await extract_text_from_receipt("/path/to/receipt.jpg")
print(f"Method: {result.method}, Confidence: {result.confidence:.0%}")
```

### Available Providers

#### 1. TextractProvider (Production Default)
- **Location:** `packages/parsers/ocr/provider_textract.py`
- **Purpose:** High-quality OCR for images (95%+ confidence)
- **Requirements:** AWS credentials, boto3
- **Supported files:** JPG, PNG, HEIC, HEIF, TIFF, BMP
- **Cost:** $0.0015 per page

#### 2. TesseractProvider (Optional, PDF fallback)
- **Location:** `packages/parsers/ocr/provider_tesseract.py`
- **Purpose:** Free OCR for scanned PDFs
- **Requirements:** `tesseract-ocr` system package, pytesseract (optional Python package)
- **Supported files:** PDF only
- **Cost:** Free
- **Threshold:** 96% confidence required, otherwise falls back to Textract

#### 3. PDFTextExtractor (Built-in)
- **Location:** `packages/parsers/ocr/provider_tesseract.py`
- **Purpose:** Fast extraction from text-based PDFs
- **Requirements:** pypdf (always installed)
- **Supported files:** PDF with embedded text
- **Cost:** Free
- **Confidence:** 100% (direct extraction)

### OCR Strategy by File Type

**Images** (JPG, PNG, HEIC, TIFF, BMP):
```
Textract ONLY → 95%+ confidence guaranteed
```

**PDFs**:
```
1. PDF Text Extraction (100% confidence, free, instant)
   ↓ (if no text found)
2. Tesseract OCR (free, requires ≥96% confidence)
   ↓ (if confidence < 96% or Tesseract disabled)
3. Textract Fallback (95%+ confidence, paid)
```

## Configuration

### Environment Variables

```bash
# OCR Backend Selection
OCR_BACKEND=auto              # auto, textract, tesseract (default: auto)

# Textract Configuration
TEXTRACT_FALLBACK_ENABLED=true   # Enable AWS Textract (default: true)
AWS_TEXTRACT_REGION=us-east-1    # AWS region (default: us-east-1)
AWS_ACCESS_KEY_ID=<your-key>
AWS_SECRET_ACCESS_KEY=<your-secret>

# Tesseract Configuration (optional)
TESSERACT_PATH=/usr/bin/tesseract           # Path to binary (auto-detected)
TESSERACT_CONFIDENCE_THRESHOLD=0.96         # Min confidence 0-1 (default: 0.96)
```

### OCR_BACKEND Options

- **`auto`** (default): Use Textract for images, PDF strategy (text → Tesseract → Textract)
- **`textract`**: Force Textract for everything (disables Tesseract)
- **`tesseract`**: Enable Tesseract for PDFs, keep Textract for images

## Installation

### Standard Installation (Textract only)

```bash
poetry install
```

This installs:
- Textract support (boto3)
- PDF text extraction (pypdf)
- Image processing (Pillow, pillow-heif, pdf2image)

**Does NOT include:** Tesseract

### With Tesseract Support (optional)

```bash
# Install Python package
poetry install --extras tesseract

# Install system dependency (worker container only)
# Already in worker Dockerfile: apt-get install tesseract-ocr
```

## File Structure

```
packages/parsers/ocr/
├── __init__.py              # Public API
├── base.py                  # OcrProvider protocol, OcrResult dataclass
├── factory.py               # OcrProviderFactory, get_ocr_factory()
├── provider_textract.py     # AWS Textract provider
└── provider_tesseract.py    # Tesseract + PDF text extraction
```

## Usage Examples

### Basic Usage (Automatic Strategy)

```python
from packages.parsers.ocr import extract_text_from_receipt

# Factory automatically selects provider based on file type
result = await extract_text_from_receipt("/path/to/receipt.jpg")

print(f"Method: {result.method}")           # textract, tesseract, pdf_text_extraction
print(f"Confidence: {result.confidence}")   # 0.0 - 1.0
print(f"Pages: {result.page_count}")
print(f"Text: {result.text}")
print(f"Bounding boxes: {len(result.bounding_boxes)}")
```

### Explicit Provider Selection

```python
from packages.parsers.ocr.factory import OcrProviderFactory

# Create factory with specific config
factory = OcrProviderFactory(
    textract_enabled=True,
    tesseract_enabled=False,  # Disable Tesseract
    aws_region="us-east-1"
)

result = await factory.extract_text("/path/to/receipt.pdf")
```

### Direct Provider Usage

```python
from packages.parsers.ocr.provider_textract import TextractProvider

provider = TextractProvider(aws_region="us-east-1")
result = await provider.extract_text("/path/to/receipt.jpg")
```

## Docker Container Setup

### Worker Container (Has Tesseract)

The worker container includes Tesseract for PDF processing:

```dockerfile
# infra/docker/worker/Dockerfile
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev
```

**Environment:**
```yaml
# docker-compose.yml - worker service
environment:
  - TESSERACT_PATH=/usr/bin/tesseract
  - TESSERACT_CONFIDENCE_THRESHOLD=0.96
  - TEXTRACT_FALLBACK_ENABLED=true
```

### API Container (No Tesseract)

The API container does NOT have Tesseract:

```yaml
# docker-compose.yml - api service
environment:
  - TEXTRACT_FALLBACK_ENABLED=true  # Only Textract
  # No TESSERACT_PATH
```

## Migration from Old Architecture

### Old Code (Monolithic)

```python
from packages.parsers.ocr_engine import extract_text_from_receipt

result = await extract_text_from_receipt("/path/to/receipt.jpg")
```

### New Code (Provider Pattern)

```python
from packages.parsers.ocr import extract_text_from_receipt

# Same API! But now uses pluggable providers
result = await extract_text_from_receipt("/path/to/receipt.jpg")
```

**Changes:**
- Import path: `packages.parsers.ocr_engine` → `packages.parsers.ocr`
- Implementation: Monolithic class → Provider pattern with factory
- Tesseract: Always required → Optional extra

### Deprecated Files

These files are replaced by the new provider architecture:

- `packages/parsers/ocr_engine.py` - Replace with `packages/parsers/ocr/factory.py`
- `packages/parsers/textract_fallback.py` - Integrated into `provider_textract.py`

**Do not delete yet** - kept for reference during migration period.

## Testing

### Run OCR Tests

```bash
# Unit tests (fast, mocked providers)
make test-unit

# Integration tests (requires AWS credentials)
make test-integration

# Test specific provider
docker compose exec worker pytest tests/unit/parsers/ocr/ -v
```

### Test Without Tesseract

```bash
# Set OCR_BACKEND to force Textract-only mode
export OCR_BACKEND=textract
export TEXTRACT_FALLBACK_ENABLED=true

docker compose exec worker pytest tests/integration/test_ocr.py -v
```

## Cost Optimization

### Current Strategy (Optimal)

| File Type | Method | Cost | Confidence |
|-----------|--------|------|------------|
| Images | Textract | $0.0015/page | 95%+ |
| Text PDFs | Direct extraction | $0 | 100% |
| Scanned PDFs | Tesseract → Textract | $0 → $0.0015 | 96%+ |

**Expected monthly cost:** $5-15 (assuming 5-10 receipts/day, 20% scanned PDFs)

### Alternative: Textract-Only (Simpler)

```bash
OCR_BACKEND=textract
TEXTRACT_FALLBACK_ENABLED=true
```

| File Type | Method | Cost | Confidence |
|-----------|--------|------|------------|
| All files | Textract | $0.0015/page | 95%+ |

**Expected monthly cost:** $10-20 (no free tier)

**Trade-off:** Simpler setup, no Tesseract dependency, slightly higher cost.

## Troubleshooting

### "Tesseract provider requires pytesseract package"

**Cause:** Tesseract is enabled but pytesseract not installed.

**Solution:**
```bash
poetry install --extras tesseract
```

Or disable Tesseract:
```bash
export OCR_BACKEND=textract
```

### "Images require Textract for production quality, but Textract is disabled"

**Cause:** `TEXTRACT_FALLBACK_ENABLED=false` but processing an image.

**Solution:**
```bash
export TEXTRACT_FALLBACK_ENABLED=true
```

Images always require Textract for production quality (95%+ confidence).

### "Textract is disabled but is needed for scanned PDF processing"

**Cause:** Both Textract and Tesseract are disabled, or Tesseract confidence too low.

**Solution:**
- Enable Textract: `TEXTRACT_FALLBACK_ENABLED=true`
- Or lower Tesseract threshold: `TESSERACT_CONFIDENCE_THRESHOLD=0.90`

## Best Practices

1. **Use Textract for images** - Always. Tesseract produces low-quality results for photos.
2. **Keep Tesseract enabled for PDFs** - Free tier saves costs on scanned PDFs.
3. **Set 96% confidence threshold** - Ensures high-quality data enters the system.
4. **Monitor OCR costs** - Track `result.method` to see Textract usage.
5. **Test both providers** - Ensure fallback logic works correctly.

## Future Enhancements

- [ ] Add GPT-4V provider for complex receipts (handwritten, damaged)
- [ ] Multi-page PDF support in Textract provider
- [ ] Parallel page processing for large PDFs
- [ ] OCR result caching (content hash → text)
- [ ] Provider health monitoring and automatic failover
- [ ] Support for Google Cloud Vision API as alternative

## Related Documentation

- [CLAUDE.md](../CLAUDE.md) - Project architecture and OCR policy (lines 152-155)
- [PARSER_ARCHITECTURE_OVERHAUL.md](./PARSER_ARCHITECTURE_OVERHAUL.md) - Why Textract-first
- [PHASE1_OCR_UPGRADE_COMPLETE.md](./PHASE1_OCR_UPGRADE_COMPLETE.md) - Previous OCR implementation
