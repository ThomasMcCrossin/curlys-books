"""
Tesseract OCR Engine - Primary OCR for receipt processing

Uses pytesseract wrapper for Tesseract OCR engine.
Processes PDF receipts page-by-page and extracts text with confidence scoring.
"""
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

import structlog
from pdf2image import convert_from_path
from PIL import Image
import pytesseract
from pillow_heif import register_heif_opener

# Register HEIF/HEIC support in Pillow
register_heif_opener()

logger = structlog.get_logger()


@dataclass
class OCRResult:
    """Result from OCR extraction"""
    text: str
    confidence: float  # 0.0 to 1.0
    page_count: int
    method: str = "tesseract"

    def __post_init__(self):
        """Ensure confidence is in valid range"""
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")


class TesseractOCR:
    """
    Tesseract OCR engine for receipt text extraction.

    Features:
    - PDF to image conversion
    - Page-by-page OCR
    - Confidence scoring
    - Automatic preprocessing
    """

    def __init__(
        self,
        tesseract_path: Optional[str] = None,
        confidence_threshold: float = 0.90
    ):
        """
        Initialize Tesseract OCR engine.

        Args:
            tesseract_path: Path to tesseract binary (auto-detected if None)
            confidence_threshold: Minimum confidence to accept (0.0-1.0)
        """
        self.confidence_threshold = confidence_threshold

        # Set tesseract path if provided
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

        logger.info("tesseract_initialized",
                   threshold=confidence_threshold,
                   path=tesseract_path or "auto-detected")

    async def extract_text(self, file_path: str) -> OCRResult:
        """
        Extract text from PDF or image file.

        Args:
            file_path: Path to PDF or image file

        Returns:
            OCRResult with extracted text and confidence

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file type not supported
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info("ocr_started",
                   file=str(file_path),
                   size_bytes=file_path.stat().st_size)

        # Determine file type
        suffix = file_path.suffix.lower()

        if suffix == '.pdf':
            return await self._extract_from_pdf(file_path)
        elif suffix in ['.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.heic', '.heif']:
            return await self._extract_from_image(file_path)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

    async def _extract_from_pdf(self, pdf_path: Path) -> OCRResult:
        """
        Extract text from PDF file.

        Converts PDF pages to images, then runs OCR on each page.

        Args:
            pdf_path: Path to PDF file

        Returns:
            OCRResult with combined text from all pages
        """
        try:
            # Convert PDF to images (one per page)
            images = convert_from_path(
                str(pdf_path),
                dpi=300,  # High DPI for better OCR
                grayscale=True  # Grayscale reduces noise
            )

            logger.info("pdf_converted_to_images",
                       page_count=len(images),
                       file=str(pdf_path))

            # Extract text from each page
            page_texts = []
            page_confidences = []

            for page_num, image in enumerate(images, start=1):
                # Get text and confidence data
                data = pytesseract.image_to_data(
                    image,
                    output_type=pytesseract.Output.DICT,
                    config='--psm 6'  # Assume uniform block of text
                )

                # Extract text
                page_text = pytesseract.image_to_string(
                    image,
                    config='--psm 6'
                )

                # Calculate average confidence (filter out empty detections)
                confidences = [
                    int(conf) for conf, text in zip(data['conf'], data['text'])
                    if conf != -1 and text.strip()
                ]

                avg_confidence = sum(confidences) / len(confidences) if confidences else 0

                logger.info("page_ocr_complete",
                           page=page_num,
                           chars=len(page_text),
                           confidence=avg_confidence)

                page_texts.append(page_text)
                page_confidences.append(avg_confidence)

            # Combine all pages
            combined_text = "\n\n--- PAGE BREAK ---\n\n".join(page_texts)
            overall_confidence = sum(page_confidences) / len(page_confidences) if page_confidences else 0

            # Convert confidence from 0-100 to 0-1
            overall_confidence = overall_confidence / 100

            logger.info("ocr_complete",
                       pages=len(images),
                       total_chars=len(combined_text),
                       confidence=overall_confidence,
                       meets_threshold=overall_confidence >= self.confidence_threshold)

            return OCRResult(
                text=combined_text,
                confidence=overall_confidence,
                page_count=len(images),
                method="tesseract"
            )

        except Exception as e:
            logger.error("ocr_failed",
                        error=str(e),
                        file=str(pdf_path),
                        exc_info=True)
            raise

    async def _extract_from_image(self, image_path: Path) -> OCRResult:
        """
        Extract text from image file.

        Args:
            image_path: Path to image file

        Returns:
            OCRResult with extracted text
        """
        try:
            # Load image
            image = Image.open(image_path)

            # Convert HEIC/HEIF to RGB for Tesseract compatibility
            if image_path.suffix.lower() in ['.heic', '.heif']:
                # Convert to RGB and create a new Image object that Tesseract can handle
                rgb_image = image.convert('RGB') if image.mode != 'RGB' else image
                # Create new Image from the data to lose the HEIF format attribute
                import io
                buffer = io.BytesIO()
                rgb_image.save(buffer, format='PNG')
                buffer.seek(0)
                image = Image.open(buffer)

            # Get confidence data
            data = pytesseract.image_to_data(
                image,
                output_type=pytesseract.Output.DICT,
                config='--psm 6'
            )

            # Extract text
            text = pytesseract.image_to_string(
                image,
                config='--psm 6'
            )

            # Calculate average confidence
            confidences = [
                int(conf) for conf, txt in zip(data['conf'], data['text'])
                if conf != -1 and txt.strip()
            ]

            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            avg_confidence = avg_confidence / 100  # Convert to 0-1

            logger.info("image_ocr_complete",
                       chars=len(text),
                       confidence=avg_confidence)

            return OCRResult(
                text=text,
                confidence=avg_confidence,
                page_count=1,
                method="tesseract"
            )

        except Exception as e:
            logger.error("image_ocr_failed",
                        error=str(e),
                        file=str(image_path),
                        exc_info=True)
            raise


# Singleton instance for easy import
ocr_engine = TesseractOCR(
    tesseract_path=os.getenv('TESSERACT_PATH', '/usr/bin/tesseract'),
    confidence_threshold=float(os.getenv('TESSERACT_CONFIDENCE_THRESHOLD', '0.90'))
)


async def extract_text_from_receipt(file_path: str) -> OCRResult:
    """
    Convenience function for OCR extraction.

    Args:
        file_path: Path to receipt file (PDF or image)

    Returns:
        OCRResult with extracted text and confidence

    Example:
        ```python
        from packages.parsers.ocr_engine import extract_text_from_receipt

        result = await extract_text_from_receipt("/path/to/receipt.pdf")
        if result.confidence >= 0.90:
            print(f"High confidence text:\n{result.text}")
        else:
            print(f"Low confidence ({result.confidence}), use Textract")
        ```
    """
    return await ocr_engine.extract_text(file_path)
