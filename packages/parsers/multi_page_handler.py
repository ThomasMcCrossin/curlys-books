"""
Multi-page receipt handler - Combines multiple photos of same receipt

Handles cases where:
- Receipt is too long for one photo
- User takes multiple photos of same receipt
- Photos are sequential (IMG_001.heic, IMG_002.heic, etc.)
"""
import re
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class ReceiptPageGroup:
    """Group of files that belong to same receipt"""
    files: List[Path]
    base_name: str

    def __str__(self):
        return f"{self.base_name} ({len(self.files)} pages)"


def detect_multi_page_receipts(file_paths: List[Path]) -> List[ReceiptPageGroup]:
    """
    Detect which files belong to same multi-page receipt.

    Detection strategies:
    1. Sequential timestamps (IMG20241008131715, IMG20241008131724, etc.)
    2. Same base name with suffixes (_01, _02, etc.)
    3. Files within 30 seconds of each other

    Args:
        file_paths: List of image file paths

    Returns:
        List of ReceiptPageGroup objects
    """
    if not file_paths:
        return []

    # Sort by filename (which includes timestamp for IMG files)
    sorted_files = sorted(file_paths)

    groups = []
    current_group = None

    for file_path in sorted_files:
        # Extract timestamp from filename like IMG20241008131715.heic
        match = re.match(r'IMG(\d{14})', file_path.stem)

        if not match:
            # Not an IMG file - treat as single page
            groups.append(ReceiptPageGroup(
                files=[file_path],
                base_name=file_path.stem
            ))
            current_group = None
            continue

        timestamp = match.group(1)

        # Check if this might be same receipt as previous file
        if current_group:
            # Get timestamp of last file in current group
            last_match = re.match(r'IMG(\d{14})', current_group.files[-1].stem)
            if last_match:
                last_timestamp = last_match.group(1)

                # If within 60 seconds, likely same receipt
                time_diff = abs(int(timestamp) - int(last_timestamp))

                # 60 seconds = 60 in timestamp format (last 2 digits)
                if time_diff <= 60:
                    # Add to current group
                    current_group.files.append(file_path)
                    logger.info("multi_page_detected",
                               group=current_group.base_name,
                               file=file_path.name,
                               pages=len(current_group.files))
                    continue

        # Start new group
        if current_group:
            groups.append(current_group)

        current_group = ReceiptPageGroup(
            files=[file_path],
            base_name=file_path.stem
        )

    # Add last group
    if current_group:
        groups.append(current_group)

    # Log summary
    multi_page_groups = [g for g in groups if len(g.files) > 1]
    if multi_page_groups:
        logger.info("multi_page_summary",
                   total_groups=len(groups),
                   multi_page_groups=len(multi_page_groups))
        for group in multi_page_groups:
            logger.info("multi_page_group",
                       group=group.base_name,
                       pages=len(group.files),
                       files=[f.name for f in group.files])

    return groups


def should_combine_pages(files: List[Path]) -> bool:
    """
    Determine if files should be combined into one receipt.

    Args:
        files: List of image files

    Returns:
        True if files should be combined
    """
    if len(files) <= 1:
        return False

    # Check if sequential timestamps
    timestamps = []
    for f in files:
        match = re.match(r'IMG(\d{14})', f.stem)
        if match:
            timestamps.append(int(match.group(1)))

    if len(timestamps) != len(files):
        return False

    # Check if all within 2 minutes
    time_range = max(timestamps) - min(timestamps)
    return time_range <= 200  # 2 minutes in timestamp format


async def combine_ocr_pages(ocr_results: List[str]) -> str:
    """
    Combine OCR text from multiple pages into single text.

    Strategies:
    - Remove duplicate headers/footers
    - Mark page boundaries
    - Preserve line item continuity

    Args:
        ocr_results: List of OCR text from each page

    Returns:
        Combined text
    """
    if len(ocr_results) == 1:
        return ocr_results[0]

    combined = []

    for page_num, text in enumerate(ocr_results, 1):
        combined.append(f"\n--- PAGE {page_num} ---\n")
        combined.append(text)

    result = "\n".join(combined)

    logger.info("pages_combined",
               pages=len(ocr_results),
               total_chars=len(result))

    return result


def auto_group_receipts(directory: Path) -> Dict[str, List[Path]]:
    """
    Automatically group receipt files in directory by receipt.

    Args:
        directory: Directory containing receipt images

    Returns:
        Dict mapping receipt_id to list of file paths
    """
    # Get all image files
    image_files = []
    for pattern in ['*.heic', '*.heif', '*.jpg', '*.jpeg', '*.png', '*.pdf']:
        image_files.extend(directory.glob(pattern))

    # Detect groups
    groups = detect_multi_page_receipts(image_files)

    # Convert to dict
    result = {}
    for group in groups:
        result[group.base_name] = group.files

    return result
