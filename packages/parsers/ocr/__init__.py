"""
OCR Package

Provides pluggable OCR providers with a factory pattern.

Main entry point:
    from packages.parsers.ocr import extract_text_from_receipt

    result = await extract_text_from_receipt("/path/to/receipt.jpg")

Available providers:
    - TextractProvider: AWS Textract (production quality, 95%+ confidence)
    - TesseractProvider: Tesseract OCR (optional, for PDF fallback)
    - PDFTextExtractor: Direct PDF text extraction (fast, for text-based PDFs)

Configuration via environment:
    - TEXTRACT_FALLBACK_ENABLED: Enable AWS Textract (default: true)
    - OCR_BACKEND: Preference (auto, textract, tesseract)
    - TESSERACT_PATH: Path to tesseract binary
    - TESSERACT_CONFIDENCE_THRESHOLD: Min confidence (default: 0.96)
"""
from packages.parsers.ocr.base import OcrResult, OcrProvider
from packages.parsers.ocr.factory import (
    OcrProviderFactory,
    extract_text_from_receipt,
    get_ocr_factory,
)
from packages.parsers.ocr.provider_textract import TextractProvider

__all__ = [
    "OcrResult",
    "OcrProvider",
    "OcrProviderFactory",
    "TextractProvider",
    "extract_text_from_receipt",
    "get_ocr_factory",
]
