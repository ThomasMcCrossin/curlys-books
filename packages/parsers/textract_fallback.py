"""
AWS Textract Fallback - High-quality OCR for low-confidence receipts

Used when Tesseract confidence < 90% threshold.
More expensive but handles:
- Faded thermal receipts
- Crumpled/damaged receipts
- Complex layouts
- Handwritten notes

Cost: ~$1.50 per 1000 pages
"""
import os
from pathlib import Path
from typing import Optional

import boto3
import structlog

from packages.parsers.ocr_engine import OCRResult

logger = structlog.get_logger()


class TextractFallback:
    """
    AWS Textract service for high-quality OCR.

    Automatically handles:
    - PDF to image conversion (done by AWS)
    - Table detection
    - Form field extraction
    - High confidence even on poor quality receipts
    """

    def __init__(
        self,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        region_name: str = "us-east-1"
    ):
        """
        Initialize Textract client.

        Args:
            aws_access_key_id: AWS access key (from env if None)
            aws_secret_access_key: AWS secret key (from env if None)
            region_name: AWS region for Textract
        """
        self.client = boto3.client(
            'textract',
            aws_access_key_id=aws_access_key_id or os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=aws_secret_access_key or os.getenv('AWS_SECRET_ACCESS_KEY'),
            region_name=region_name
        )

        self.region = region_name
        logger.info("textract_initialized", region=region_name)

    async def extract_text(self, file_path: str) -> OCRResult:
        """
        Extract text using AWS Textract.

        Args:
            file_path: Path to receipt file (PDF or image)

        Returns:
            OCRResult with extracted text and confidence

        Raises:
            FileNotFoundError: If file doesn't exist
            Exception: If Textract API call fails
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info("textract_started",
                   file=str(file_path),
                   size_bytes=file_path.stat().st_size)

        try:
            # Convert HEIC to JPG if needed (Textract doesn't support HEIC)
            if file_path.suffix.lower() in ['.heic', '.heif']:
                from PIL import Image
                from pillow_heif import register_heif_opener
                import io

                register_heif_opener()

                logger.info("converting_heic_to_jpg", file=str(file_path))

                # Load HEIC and convert to JPG
                img = Image.open(file_path)
                rgb_img = img.convert('RGB') if img.mode != 'RGB' else img

                # Convert to JPG bytes
                buffer = io.BytesIO()
                rgb_img.save(buffer, format='JPEG', quality=95)
                file_bytes = buffer.getvalue()

                logger.info("heic_converted", original_size=file_path.stat().st_size, jpg_size=len(file_bytes))
            else:
                # Read file bytes directly
                with open(file_path, 'rb') as f:
                    file_bytes = f.read()

            # Call Textract
            response = self.client.detect_document_text(
                Document={'Bytes': file_bytes}
            )

            # Extract text blocks and bounding boxes
            text_blocks = []
            confidences = []
            bounding_boxes = []

            for block in response.get('Blocks', []):
                if block['BlockType'] == 'LINE':
                    text_blocks.append(block['Text'])
                    confidences.append(block.get('Confidence', 0))

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

            # Combine text
            combined_text = '\n'.join(text_blocks)

            # Calculate average confidence
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            avg_confidence = avg_confidence / 100  # Convert from 0-100 to 0-1

            # Get page count from metadata (defaults to 1 if not provided)
            doc_metadata = response.get('DocumentMetadata', {})
            page_count = doc_metadata.get('Pages', 1) if isinstance(doc_metadata.get('Pages'), int) else 1

            logger.info("textract_complete",
                       blocks=len(text_blocks),
                       chars=len(combined_text),
                       confidence=avg_confidence,
                       pages=page_count,
                       bounding_boxes=len(bounding_boxes))

            return OCRResult(
                text=combined_text,
                confidence=avg_confidence,
                page_count=page_count,
                method="textract",
                bounding_boxes=bounding_boxes
            )

        except Exception as e:
            logger.error("textract_failed",
                        error=str(e),
                        file=str(file_path),
                        exc_info=True)
            raise


# Singleton instance for easy import
textract_fallback = TextractFallback(
    region_name=os.getenv('AWS_TEXTRACT_REGION', 'us-east-1')
)


async def extract_with_textract(file_path: str) -> OCRResult:
    """
    Convenience function for Textract extraction.

    Args:
        file_path: Path to receipt file (PDF or image)

    Returns:
        OCRResult with extracted text and confidence

    Example:
        ```python
        from packages.parsers.textract_fallback import extract_with_textract

        # When Tesseract confidence is low
        result = await extract_with_textract("/path/to/faded_receipt.pdf")
        print(f"Textract confidence: {result.confidence}")
        print(f"Text:\n{result.text}")
        ```
    """
    return await textract_fallback.extract_text(file_path)
