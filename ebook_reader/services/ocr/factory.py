from django.conf import settings

from .exceptions import OcrConfigurationError
from .tesseract_engine import TesseractOcrEngine


def get_ocr_engine(engine_name=None):
    selected_engine = (engine_name or settings.EBOOK_OCR_ENGINE).lower()
    if selected_engine == "tesseract":
        return TesseractOcrEngine(
            languages=settings.EBOOK_OCR_LANGUAGES,
            timeout=settings.EBOOK_OCR_TIMEOUT_SECONDS,
            preprocessing=settings.EBOOK_OCR_PREPROCESSING,
            config=getattr(settings, "EBOOK_OCR_TESSERACT_CONFIG", ""),
        )
    raise OcrConfigurationError(f"Unknown OCR engine: {selected_engine}")
