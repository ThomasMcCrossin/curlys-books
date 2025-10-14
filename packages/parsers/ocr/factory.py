"""
OCR Provider Factory

Creates appropriate OCR provider based on configuration and file type.
Implements the strategy pattern for OCR provider selection.
"""
import os
from pathlib import Path
from typing import Optional

import structlog

from packages.parsers.ocr.base import OcrProvider, OcrResult
from packages.parsers.ocr.provider_textract import TextractProvider

logger = structlog.get_logger()


class OcrProviderFactory:
    """
    Factory for creating OCR providers based on configuration.

    Strategy:
    - Images: Always use Textract (production quality, 95%+ confidence)
    - PDFs: Try text extraction → Tesseract (if enabled) → Textract fallback
    """

    def __init__(
        self,
        textract_enabled: bool = True,
        tesseract_enabled: bool = True,
        aws_region: str = "us-east-1",
        tesseract_path: Optional[str] = None,
        tesseract_confidence_threshold: float = 0.96
    ):
        """
        Initialize OCR factory with configuration.

        Args:
            textract_enabled: Enable AWS Textract (default: True)
            tesseract_enabled: Enable Tesseract for PDFs (default: True)
            aws_region: AWS region for Textract
            tesseract_path: Path to tesseract binary (auto-detected if None)
            tesseract_confidence_threshold: Min confidence for Tesseract (0.96 = 96%)
        """
        self.textract_enabled = textract_enabled
        self.tesseract_enabled = tesseract_enabled
        self.aws_region = aws_region
        self.tesseract_path = tesseract_path
        self.tesseract_confidence_threshold = tesseract_confidence_threshold

        # Initialize providers lazily
        self._textract_provider: Optional[TextractProvider] = None
        self._tesseract_provider = None
        self._pdf_text_extractor = None

        logger.info("ocr_factory_initialized",
                   textract_enabled=textract_enabled,
                   tesseract_enabled=tesseract_enabled,
                   tesseract_threshold=tesseract_confidence_threshold)

    @property
    def textract_provider(self) -> TextractProvider:
        """Lazy-load Textract provider"""
        if not self.textract_enabled:
            raise RuntimeError("Textract is disabled but was requested")

        if self._textract_provider is None:
            self._textract_provider = TextractProvider(aws_region=self.aws_region)

        return self._textract_provider

    @property
    def tesseract_provider(self):
        """Lazy-load Tesseract provider (only if enabled)"""
        if not self.tesseract_enabled:
            raise RuntimeError("Tesseract is disabled but was requested")

        if self._tesseract_provider is None:
            # Lazy import to avoid dependency when tesseract disabled
            from packages.parsers.ocr.provider_tesseract import TesseractProvider
            self._tesseract_provider = TesseractProvider(
                tesseract_path=self.tesseract_path,
                confidence_threshold=self.tesseract_confidence_threshold
            )

        return self._tesseract_provider

    @property
    def pdf_text_extractor(self):
        """Lazy-load PDF text extractor"""
        if self._pdf_text_extractor is None:
            from packages.parsers.ocr.provider_tesseract import PDFTextExtractor
            self._pdf_text_extractor = PDFTextExtractor()

        return self._pdf_text_extractor

    async def extract_text(self, file_path: str | Path) -> OcrResult:
        """
        Extract text from file using appropriate OCR strategy.

        Strategy by file type:
        - Images: Textract only (production quality)
        - PDFs: Text extraction → Tesseract (if enabled) → Textract fallback

        Args:
            file_path: Path to file to process

        Returns:
            OcrResult with extracted text and metadata

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file type not supported
            RuntimeError: If all OCR methods fail
        """
        file_path = Path(file_path)
        file_ext = file_path.suffix.lower()

        logger.info("ocr_extract_started",
                   file=str(file_path),
                   file_type=file_ext,
                   size_bytes=file_path.stat().st_size)

        # IMAGES: Use Textract only
        if file_ext in {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}:
            return await self._extract_from_image(file_path)

        # PDFs: Multi-stage strategy
        elif file_ext == '.pdf':
            return await self._extract_from_pdf(file_path)

        else:
            raise ValueError(f"Unsupported file type: {file_ext}")

    async def _extract_from_image(self, image_path: Path) -> OcrResult:
        """
        Extract text from image using Textract.

        Policy: Images always use Textract for production quality (95%+ confidence).
        """
        if not self.textract_enabled:
            raise RuntimeError(
                "Images require Textract for production quality, but Textract is disabled. "
                "Set TEXTRACT_FALLBACK_ENABLED=true in environment."
            )

        logger.info("ocr_using_textract_for_image", file=str(image_path))
        return await self.textract_provider.extract_text(image_path)

    async def _extract_from_pdf(self, pdf_path: Path) -> OcrResult:
        """
        Extract text from PDF using multi-stage strategy.

        Strategy:
        1. Try direct text extraction (fast, 100% accurate for text-based PDFs)
        2. If scanned PDF, try Tesseract (if enabled, requires ≥96% confidence)
        3. Fall back to Textract if Tesseract confidence too low or disabled

        Args:
            pdf_path: Path to PDF file

        Returns:
            OcrResult from the successful extraction method
        """
        logger.info("ocr_pdf_strategy", file=str(pdf_path))

        # STAGE 1: Try direct text extraction
        try:
            result = await self.pdf_text_extractor.extract_text(pdf_path)
            logger.info("pdf_text_extraction_success",
                       chars=len(result.text),
                       pages=result.page_count)
            return result

        except ValueError as e:
            # Scanned PDF - need OCR
            logger.info("pdf_requires_ocr",
                       reason=str(e),
                       message="PDF appears to be scanned")

        except Exception as e:
            logger.warning("pdf_text_extraction_failed",
                          error=str(e),
                          message="Falling back to OCR")

        # STAGE 2: Try Tesseract (if enabled)
        if self.tesseract_enabled:
            try:
                logger.info("pdf_trying_tesseract",
                           threshold=self.tesseract_confidence_threshold)

                result = await self.tesseract_provider.extract_text(pdf_path)

                # Check if confidence meets threshold
                if result.confidence >= self.tesseract_confidence_threshold:
                    logger.info("tesseract_confidence_acceptable",
                               confidence=result.confidence,
                               threshold=self.tesseract_confidence_threshold)
                    return result
                else:
                    logger.warning("tesseract_confidence_too_low",
                                  confidence=result.confidence,
                                  threshold=self.tesseract_confidence_threshold,
                                  message="Falling back to Textract")

            except Exception as e:
                logger.error("tesseract_failed",
                            error=str(e),
                            message="Falling back to Textract")

        else:
            logger.info("tesseract_disabled", message="Skipping Tesseract, using Textract")

        # STAGE 3: Fall back to Textract
        if not self.textract_enabled:
            raise RuntimeError(
                "Textract is disabled but is needed for scanned PDF processing. "
                "Either enable Textract or enable Tesseract with lower threshold."
            )

        logger.info("pdf_using_textract_fallback")

        # Convert first page to image for Textract (TODO: multi-page support)
        from pdf2image import convert_from_path
        images = convert_from_path(str(pdf_path), dpi=300, first_page=1, last_page=1)

        if not images:
            raise RuntimeError(f"Failed to convert PDF to image: {pdf_path}")

        # Save temporary image for Textract
        temp_image_path = pdf_path.parent / f"{pdf_path.stem}_page1.jpg"
        images[0].save(temp_image_path, "JPEG", quality=95)

        try:
            result = await self.textract_provider.extract_text(temp_image_path)
            logger.info("textract_complete",
                       chars=len(result.text),
                       confidence=result.confidence)
            return OcrResult(
                text=result.text,
                confidence=result.confidence,
                page_count=1,  # TODO: Multi-page support
                method="textract_fallback",
                bounding_boxes=result.bounding_boxes
            )
        finally:
            # Clean up temporary image
            if temp_image_path.exists():
                temp_image_path.unlink()


# Singleton factory instance (configured from environment)
_default_factory: Optional[OcrProviderFactory] = None


def get_ocr_factory() -> OcrProviderFactory:
    """
    Get the default OCR factory instance (singleton).

    Factory is configured from environment variables:
    - TEXTRACT_FALLBACK_ENABLED: Enable AWS Textract (default: true)
    - OCR_BACKEND: OCR backend preference (textract, tesseract, or auto)
    - AWS_TEXTRACT_REGION: AWS region (default: us-east-1)
    - TESSERACT_PATH: Path to tesseract binary
    - TESSERACT_CONFIDENCE_THRESHOLD: Min confidence (default: 0.96)

    Returns:
        Configured OcrProviderFactory instance
    """
    global _default_factory

    if _default_factory is None:
        # Read configuration from environment
        textract_enabled = os.getenv('TEXTRACT_FALLBACK_ENABLED', 'true').lower() == 'true'
        ocr_backend = os.getenv('OCR_BACKEND', 'auto').lower()  # auto, textract, tesseract

        # Determine if Tesseract should be enabled
        if ocr_backend == 'tesseract':
            tesseract_enabled = True
        elif ocr_backend == 'textract':
            tesseract_enabled = False
        else:
            # Auto mode: enable Tesseract for PDF fallback if available
            tesseract_enabled = True

        _default_factory = OcrProviderFactory(
            textract_enabled=textract_enabled,
            tesseract_enabled=tesseract_enabled,
            aws_region=os.getenv('AWS_TEXTRACT_REGION', 'us-east-1'),
            tesseract_path=os.getenv('TESSERACT_PATH'),
            tesseract_confidence_threshold=float(
                os.getenv('TESSERACT_CONFIDENCE_THRESHOLD', '0.96')
            )
        )

        logger.info("default_ocr_factory_created",
                   textract_enabled=textract_enabled,
                   tesseract_enabled=tesseract_enabled,
                   ocr_backend=ocr_backend)

    return _default_factory


async def extract_text_from_receipt(file_path: str | Path) -> OcrResult:
    """
    Convenience function for OCR extraction using default factory.

    This is the main entry point for OCR processing.

    Strategy:
    - Images: AWS Textract (95%+ confidence)
    - PDFs: Text extraction → Tesseract (≥96%) → Textract fallback

    Args:
        file_path: Path to receipt file (PDF or image)

    Returns:
        OcrResult with extracted text and metadata

    Example:
        ```python
        from packages.parsers.ocr.factory import extract_text_from_receipt

        result = await extract_text_from_receipt("/path/to/receipt.jpg")
        print(f"Method: {result.method}, Confidence: {result.confidence:.0%}")
        print(result.text)
        ```
    """
    factory = get_ocr_factory()
    return await factory.extract_text(file_path)
