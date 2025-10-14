"""
Tesseract OCR Provider (Optional)

Provides free OCR for PDFs when text extraction fails.
Requires tesseract-ocr system package installed.

This provider is optional and only used for scanned PDFs.
Images should always use Textract for production quality.
"""
from pathlib import Path
from typing import Optional

import structlog
from pdf2image import convert_from_path

from packages.parsers.ocr.base import OcrProvider, OcrResult

logger = structlog.get_logger()


class TesseractProvider:
    """
    Tesseract OCR provider for PDF processing.

    Only used for scanned PDFs when:
    1. Direct text extraction fails (image-based PDF)
    2. Confidence threshold of 96%+ is required
    3. Falls back to Textract if confidence too low

    NOT recommended for images in production (use Textract instead).
    """

    # Supported file types (PDFs only in production workflow)
    SUPPORTED_EXTENSIONS = {'.pdf'}

    def __init__(
        self,
        tesseract_path: Optional[str] = None,
        confidence_threshold: float = 0.96
    ):
        """
        Initialize Tesseract provider.

        Args:
            tesseract_path: Path to tesseract binary (auto-detected if None)
            confidence_threshold: Minimum confidence to accept result (0.96 = 96%)
        """
        # Lazy import to avoid dependency when provider not used
        try:
            import pytesseract
            if tesseract_path:
                pytesseract.pytesseract.tesseract_cmd = tesseract_path
            self.pytesseract = pytesseract
            logger.info("tesseract_provider_initialized",
                       threshold=confidence_threshold)
        except ImportError as e:
            logger.error("tesseract_import_failed",
                        error=str(e),
                        message="pytesseract not installed - install with: pip install pytesseract")
            raise RuntimeError("Tesseract provider requires pytesseract package") from e

        self.confidence_threshold = confidence_threshold

    def supports_file_type(self, file_path: Path) -> bool:
        """Check if file type is supported (PDFs only)"""
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    async def extract_text(self, file_path: Path) -> OcrResult:
        """
        Extract text from PDF using Tesseract OCR.

        Only processes scanned PDFs (images embedded in PDF).
        Returns result with confidence score - caller should check
        if confidence meets threshold and fall back to Textract if needed.

        Args:
            file_path: Path to PDF file

        Returns:
            OcrResult with extracted text and confidence

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file type not supported
            RuntimeError: If Tesseract processing fails
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not self.supports_file_type(file_path):
            raise ValueError(f"Unsupported file type for Tesseract: {file_path.suffix}")

        logger.info("tesseract_processing_pdf",
                   file=str(file_path),
                   threshold=self.confidence_threshold)

        try:
            # Convert PDF to images
            images = convert_from_path(
                str(file_path),
                dpi=300,
                grayscale=True
            )

            logger.info("pdf_converted_to_images", page_count=len(images))

            # Extract text from each page
            page_texts = []
            page_confidences = []

            for page_num, image in enumerate(images, start=1):
                # Get confidence data
                data = self.pytesseract.image_to_data(
                    image,
                    output_type=self.pytesseract.Output.DICT,
                    config='--psm 6'
                )

                # Extract text
                page_text = self.pytesseract.image_to_string(image, config='--psm 6')

                # Calculate confidence
                confidences = [
                    int(conf) for conf, text in zip(data['conf'], data['text'])
                    if conf != -1 and text.strip()
                ]

                avg_confidence = sum(confidences) / len(confidences) if confidences else 0

                logger.info("page_tesseract_complete",
                           page=page_num,
                           confidence=avg_confidence,
                           chars=len(page_text))

                page_texts.append(page_text)
                page_confidences.append(avg_confidence)

            combined_text = "\n\n--- PAGE BREAK ---\n\n".join(page_texts)
            overall_confidence = sum(page_confidences) / len(page_confidences) if page_confidences else 0
            overall_confidence = overall_confidence / 100  # Convert to 0-1

            logger.info("tesseract_complete",
                       pages=len(images),
                       chars=len(combined_text),
                       confidence=overall_confidence,
                       meets_threshold=overall_confidence >= self.confidence_threshold)

            return OcrResult(
                text=combined_text,
                confidence=overall_confidence,
                page_count=len(images),
                method="tesseract"
            )

        except Exception as e:
            logger.error("tesseract_failed",
                        error=str(e),
                        file=str(file_path),
                        exc_info=True)
            raise RuntimeError(f"Tesseract extraction failed: {e}") from e


class PDFTextExtractor:
    """
    Direct PDF text extraction provider.

    Attempts to extract embedded text from PDF without OCR.
    Only works for text-based PDFs (not scanned/image PDFs).
    """

    def __init__(self):
        """Initialize PDF text extractor"""
        logger.info("pdf_text_extractor_initialized")

    def supports_file_type(self, file_path: Path) -> bool:
        """Check if file type is supported (PDFs only)"""
        return file_path.suffix.lower() == '.pdf'

    async def extract_text(self, file_path: Path) -> OcrResult:
        """
        Extract embedded text from PDF.

        Args:
            file_path: Path to PDF file

        Returns:
            OcrResult with extracted text (confidence=1.0 for direct extraction)

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file type not supported or no text found
        """
        import pypdf

        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not self.supports_file_type(file_path):
            raise ValueError(f"Unsupported file type for PDF extractor: {file_path.suffix}")

        logger.info("pdf_attempting_text_extraction", file=str(file_path))

        try:
            reader = pypdf.PdfReader(str(file_path))
            page_texts = []

            for page in reader.pages:
                text = page.extract_text()
                page_texts.append(text)

            combined_text = "\n\n--- PAGE BREAK ---\n\n".join(page_texts)

            # Check if we got meaningful text
            word_count = len(combined_text.split())
            char_count = len(combined_text.strip())

            if char_count >= 50 and word_count >= 10:
                logger.info("pdf_text_extracted_successfully",
                           pages=len(reader.pages),
                           chars=char_count,
                           words=word_count)

                return OcrResult(
                    text=combined_text,
                    confidence=1.0,  # Direct text extraction is 100% accurate
                    page_count=len(reader.pages),
                    method="pdf_text_extraction"
                )
            else:
                raise ValueError(
                    f"PDF appears to be scanned (insufficient text: {word_count} words, {char_count} chars)"
                )

        except pypdf.errors.PdfReadError as e:
            logger.error("pdf_read_error", error=str(e), file=str(file_path))
            raise RuntimeError(f"Failed to read PDF: {e}") from e
        except Exception as e:
            logger.error("pdf_extraction_failed", error=str(e), file=str(file_path))
            raise
