"""
OCR Provider Base Interface

Defines the contract for all OCR providers (Textract, Tesseract, etc.)
This allows swapping OCR backends via configuration without changing calling code.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Optional, List, Dict, Any


@dataclass
class OcrResult:
    """
    Result from OCR extraction.

    Attributes:
        text: Extracted text content
        confidence: Overall confidence score (0.0 to 1.0)
        page_count: Number of pages processed
        method: Name of OCR method used (textract, tesseract, pdf_text_extraction)
        bounding_boxes: Optional list of bounding boxes with text and coordinates
    """
    text: str
    confidence: float  # 0.0 to 1.0
    page_count: int
    method: str
    bounding_boxes: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate confidence is in valid range"""
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")


class OcrProvider(Protocol):
    """
    Protocol for OCR providers.

    All OCR providers must implement this interface to be compatible
    with the OCR factory and calling code.
    """

    async def extract_text(self, file_path: Path) -> OcrResult:
        """
        Extract text from image or PDF file.

        Args:
            file_path: Path to file to process

        Returns:
            OcrResult with extracted text and metadata

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file type not supported
            RuntimeError: If OCR processing fails
        """
        ...

    def supports_file_type(self, file_path: Path) -> bool:
        """
        Check if this provider supports the given file type.

        Args:
            file_path: Path to file to check

        Returns:
            True if provider can process this file type
        """
        ...
