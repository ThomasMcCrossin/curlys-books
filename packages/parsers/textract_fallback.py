class TextractFallback:
    async def extract(file_path: str) -> OCRResult:
        # Convert PDF to bytes
        # Call AWS Textract API
        # Parse response into OCRResult format