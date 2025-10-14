"""
AWS Textract OCR Provider

Provides high-quality OCR (95%+ confidence) for images.
This is the default provider for production use.
"""
import io
from pathlib import Path
from typing import Optional

import boto3
import structlog
from PIL import Image
from pillow_heif import register_heif_opener

from packages.parsers.ocr.base import OcrProvider, OcrResult

# Register HEIF/HEIC support in Pillow
register_heif_opener()

logger = structlog.get_logger()


class TextractProvider:
    """
    AWS Textract OCR provider.

    Uses Amazon Textract for high-quality text extraction from images.
    Provides 95%+ confidence on receipts and documents.
    """

    # Supported file types (images only - PDFs handled separately)
    SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.tif', '.bmp'}

    def __init__(self, aws_region: str = "us-east-1"):
        """
        Initialize Textract provider.

        Args:
            aws_region: AWS region for Textract API
        """
        self.textract = boto3.client('textract', region_name=aws_region)
        self.region = aws_region
        logger.info("textract_provider_initialized", region=aws_region)

    def supports_file_type(self, file_path: Path) -> bool:
        """Check if file type is supported (images only)"""
        return file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    async def extract_text(self, file_path: Path) -> OcrResult:
        """
        Extract text from image using AWS Textract.

        Args:
            file_path: Path to image file

        Returns:
            OcrResult with extracted text and bounding boxes

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file type not supported
            RuntimeError: If Textract API fails
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not self.supports_file_type(file_path):
            raise ValueError(f"Unsupported file type for Textract: {file_path.suffix}")

        logger.info("textract_processing_image",
                   file=str(file_path),
                   size_bytes=file_path.stat().st_size)

        try:
            # Load and prepare image
            image = Image.open(file_path)

            # Convert HEIC/HEIF to JPG for Textract
            if file_path.suffix.lower() in ['.heic', '.heif']:
                logger.info("converting_heic_to_jpg")
                image = image.convert('RGB')

            # Convert image to bytes for Textract
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=95)
            image_bytes = buffer.getvalue()

            logger.info("calling_textract", size_bytes=len(image_bytes))

            # Call Textract API
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

            return OcrResult(
                text=text,
                confidence=avg_confidence,
                page_count=1,
                method="textract",
                bounding_boxes=bounding_boxes
            )

        except Exception as e:
            logger.error("textract_failed",
                        error=str(e),
                        file=str(file_path),
                        exc_info=True)
            raise RuntimeError(f"Textract extraction failed: {e}") from e
