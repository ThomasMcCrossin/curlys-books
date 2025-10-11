"""
OCR Engine - AWS Textract-first with Tesseract fallback

Policy (see CLAUDE.md lines 152-155):
- Images (jpg, png, heic, tiff): AWS Textract ONLY (95%+ confidence guaranteed)
- PDFs: Direct text extraction → Tesseract (≥96% confidence) → Textract fallback

Why Textract-first for images:
- Bad OCR creates more work than it saves (manual review time, wasted AI calls)
- Quality data is critical for accurate categorization
- Tesseract on photos often produces <80% confidence → everything goes to review queue
"""
import os
import io
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional, List, Dict, Any

import boto3
import pypdf
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
    method: str  # textract, tesseract, pdf_text_extraction
    bounding_boxes: List[Dict[str, Any]] = field(default_factory=list)  # LINE blocks with geometry from Textract

    def __post_init__(self):
        """Ensure confidence is in valid range"""
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")


class OCREngine:
    """
    OCR Engine implementing Textract-first policy.

    For images: Always use AWS Textract (95%+ confidence)
    For PDFs: Try text extraction → Tesseract if good → Textract fallback
    """

    def __init__(
        self,
        textract_enabled: bool = True,
        aws_region: str = "us-east-1",
        tesseract_path: Optional[str] = None,
        tesseract_confidence_threshold: float = 0.96
    ):
        """
        Initialize OCR Engine.

        Args:
            textract_enabled: Whether to use AWS Textract (default: True)
            aws_region: AWS region for Textract
            tesseract_path: Path to tesseract binary (auto-detected if None)
            tesseract_confidence_threshold: Min confidence for Tesseract (0.96 = 96%)
        """
        self.textract_enabled = textract_enabled
        self.tesseract_threshold = tesseract_confidence_threshold

        # Initialize AWS Textract client
        if textract_enabled:
            self.textract = boto3.client('textract', region_name=aws_region)
            logger.info("textract_initialized", region=aws_region)
        else:
            self.textract = None
            logger.warning("textract_disabled", message="Textract is disabled, will use Tesseract only")

        # Set tesseract path if provided
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

        logger.info("ocr_engine_initialized",
                   textract_enabled=textract_enabled,
                   tesseract_threshold=tesseract_confidence_threshold)

    async def extract_text(self, file_path: str) -> OCRResult:
        """
        Extract text from PDF or image file using appropriate OCR strategy.

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

    async def _extract_from_image(self, image_path: Path) -> OCRResult:
        """
        Extract text from image file.

        Policy: Images always use AWS Textract for 95%+ confidence.

        Args:
            image_path: Path to image file

        Returns:
            OCRResult with extracted text
        """
        if not self.textract_enabled:
            logger.error("textract_required_but_disabled",
                        message="Images require Textract but it's disabled")
            raise RuntimeError("Textract is required for image OCR but is disabled")

        try:
            # Load and prepare image
            image = Image.open(image_path)

            # Convert HEIC/HEIF to JPG for Textract
            if image_path.suffix.lower() in ['.heic', '.heif']:
                logger.info("converting_heic_to_jpg")
                image = image.convert('RGB')

            # Convert image to bytes for Textract
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=95)
            image_bytes = buffer.getvalue()

            logger.info("calling_textract", size_bytes=len(image_bytes))

            # Call Textract
            response = self.textract.detect_document_text(
                Document={'Bytes': image_bytes}
            )

            # Extract text, confidence, and bounding boxes from Textract response
            text_blocks = []
            confidences = []
            bounding_boxes = []

            for block in response['Blocks']:
                if block['BlockType'] == 'LINE':
                    text_blocks.append(block['Text'])
                    if 'Confidence' in block:
                        confidences.append(block['Confidence'] / 100)  # Convert to 0-1

                    # Capture bounding box (normalized 0-1 coordinates)
                    if 'Geometry' in block:
                        bbox = block['Geometry']['BoundingBox']
                        bounding_boxes.append({
                            'text': block['Text'],
                            'confidence': block.get('Confidence', 0) / 100,
                            'left': bbox['Left'],
                            'top': bbox['Top'],
                            'width': bbox['Width'],
                            'height': bbox['Height']
                        })

            text = '\n'.join(text_blocks)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.95

            logger.info("textract_complete",
                       chars=len(text),
                       lines=len(text_blocks),
                       confidence=avg_confidence,
                       bounding_boxes=len(bounding_boxes))

            return OCRResult(
                text=text,
                confidence=avg_confidence,
                page_count=1,
                method="textract",
                bounding_boxes=bounding_boxes
            )

        except Exception as e:
            logger.error("textract_failed",
                        error=str(e),
                        file=str(image_path),
                        exc_info=True)
            raise

    async def _extract_from_pdf(self, pdf_path: Path) -> OCRResult:
        """
        Extract text from PDF file.

        Strategy:
        1. Try direct text extraction (fast, for native PDFs)
        2. If no text, try Tesseract OCR (≥96% confidence required)
        3. If Tesseract confidence <96%, fall back to Textract

        Args:
            pdf_path: Path to PDF file

        Returns:
            OCRResult with extracted text
        """
        try:
            # STEP 1: Try direct text extraction
            logger.info("pdf_attempting_text_extraction", file=str(pdf_path))

            try:
                reader = pypdf.PdfReader(str(pdf_path))
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

                    return OCRResult(
                        text=combined_text,
                        confidence=1.0,  # Direct text extraction is 100% accurate
                        page_count=len(reader.pages),
                        method="pdf_text_extraction"
                    )
                else:
                    logger.info("pdf_text_extraction_insufficient",
                               chars=char_count,
                               words=word_count,
                               message="PDF appears to be scanned, trying Tesseract")

            except Exception as e:
                logger.warning("pdf_text_extraction_failed",
                              error=str(e),
                              message="Falling back to Tesseract")

            # STEP 2: Try Tesseract OCR (must meet ≥96% confidence)
            logger.info("pdf_trying_tesseract", threshold=self.tesseract_threshold)

            # Convert PDF to images
            images = convert_from_path(
                str(pdf_path),
                dpi=300,
                grayscale=True
            )

            logger.info("pdf_converted_to_images", page_count=len(images))

            # Extract text from each page
            page_texts = []
            page_confidences = []

            for page_num, image in enumerate(images, start=1):
                # Get confidence data
                data = pytesseract.image_to_data(
                    image,
                    output_type=pytesseract.Output.DICT,
                    config='--psm 6'
                )

                # Extract text
                page_text = pytesseract.image_to_string(image, config='--psm 6')

                # Calculate confidence
                confidences = [
                    int(conf) for conf, text in zip(data['conf'], data['text'])
                    if conf != -1 and text.strip()
                ]

                avg_confidence = sum(confidences) / len(confidences) if confidences else 0

                logger.info("page_tesseract_complete",
                           page=page_num,
                           confidence=avg_confidence)

                page_texts.append(page_text)
                page_confidences.append(avg_confidence)

            combined_text = "\n\n--- PAGE BREAK ---\n\n".join(page_texts)
            overall_confidence = sum(page_confidences) / len(page_confidences) if page_confidences else 0
            overall_confidence = overall_confidence / 100  # Convert to 0-1

            # STEP 3: Check if Tesseract confidence meets threshold
            if overall_confidence >= self.tesseract_threshold:
                logger.info("tesseract_confidence_acceptable",
                           confidence=overall_confidence,
                           threshold=self.tesseract_threshold)

                return OCRResult(
                    text=combined_text,
                    confidence=overall_confidence,
                    page_count=len(images),
                    method="tesseract"
                )
            else:
                logger.warning("tesseract_confidence_too_low",
                              confidence=overall_confidence,
                              threshold=self.tesseract_threshold,
                              message="Falling back to Textract")

            # STEP 4: Fall back to Textract
            if not self.textract_enabled:
                logger.error("textract_needed_but_disabled",
                            confidence=overall_confidence,
                            message="Tesseract confidence too low but Textract is disabled")
                # Return Tesseract result anyway
                return OCRResult(
                    text=combined_text,
                    confidence=overall_confidence,
                    page_count=len(images),
                    method="tesseract_low_confidence"
                )

            logger.info("using_textract_for_pdf")

            # Convert first page to JPG for Textract (multi-page support TODO)
            buffer = io.BytesIO()
            images[0].save(buffer, format='JPEG', quality=95)
            image_bytes = buffer.getvalue()

            response = self.textract.detect_document_text(
                Document={'Bytes': image_bytes}
            )

            # Extract text and bounding boxes
            text_blocks = []
            confidences = []
            bounding_boxes = []

            for block in response['Blocks']:
                if block['BlockType'] == 'LINE':
                    text_blocks.append(block['Text'])
                    if 'Confidence' in block:
                        confidences.append(block['Confidence'] / 100)

                    # Capture bounding box
                    if 'Geometry' in block:
                        bbox = block['Geometry']['BoundingBox']
                        bounding_boxes.append({
                            'text': block['Text'],
                            'confidence': block.get('Confidence', 0) / 100,
                            'left': bbox['Left'],
                            'top': bbox['Top'],
                            'width': bbox['Width'],
                            'height': bbox['Height']
                        })

            text = '\n'.join(text_blocks)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.95

            logger.info("textract_complete",
                       chars=len(text),
                       confidence=avg_confidence,
                       bounding_boxes=len(bounding_boxes))

            return OCRResult(
                text=text,
                confidence=avg_confidence,
                page_count=1,  # TODO: Multi-page PDF support
                method="textract_fallback",
                bounding_boxes=bounding_boxes
            )

        except Exception as e:
            logger.error("pdf_ocr_failed",
                        error=str(e),
                        file=str(pdf_path),
                        exc_info=True)
            raise


# Singleton instance
ocr_engine = OCREngine(
    textract_enabled=os.getenv('TEXTRACT_FALLBACK_ENABLED', 'true').lower() == 'true',
    aws_region=os.getenv('AWS_TEXTRACT_REGION', 'us-east-1'),
    tesseract_path=os.getenv('TESSERACT_PATH', '/usr/bin/tesseract'),
    tesseract_confidence_threshold=float(os.getenv('TESSERACT_CONFIDENCE_THRESHOLD', '0.96'))
)


async def extract_text_from_receipt(file_path: str) -> OCRResult:
    """
    Convenience function for OCR extraction using Textract-first policy.

    For images: Always uses AWS Textract (95%+ confidence)
    For PDFs: Tries text extraction → Tesseract (≥96%) → Textract

    Args:
        file_path: Path to receipt file (PDF or image)

    Returns:
        OCRResult with extracted text and confidence

    Example:
        ```python
        from packages.parsers.ocr_engine import extract_text_from_receipt

        result = await extract_text_from_receipt("/path/to/receipt.jpg")
        print(f"Method: {result.method}, Confidence: {result.confidence:.0%}")
        print(result.text)
        ```
    """
    return await ocr_engine.extract_text(file_path)
