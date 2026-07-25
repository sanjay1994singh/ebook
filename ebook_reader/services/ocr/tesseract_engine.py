import logging
import time

from PIL import Image, ImageOps

from .base import OcrResult, OcrWord, normalize_devanagari_digits
from .exceptions import OcrDependencyError, OcrProcessingError, OcrTimeoutError


logger = logging.getLogger(__name__)


class TesseractOcrEngine:
    engine_name = "tesseract"

    def __init__(
        self,
        *,
        languages="hin+eng",
        timeout=60,
        preprocessing=None,
        pytesseract_module=None,
    ):
        self.languages = languages
        self.timeout = timeout
        self.preprocessing = {
            "grayscale": True,
            "threshold": True,
            "threshold_value": 180,
            "deskew": False,
            "border_removal": False,
            **(preprocessing or {}),
        }
        self.pytesseract = pytesseract_module or self._load_pytesseract()

    def extract(self, image):
        started_at = time.monotonic()
        processed_image, warnings = preprocess_image(image, self.preprocessing)
        try:
            data = self.pytesseract.image_to_data(
                processed_image,
                lang=self.languages,
                output_type=self.pytesseract.Output.DICT,
                timeout=self.timeout,
            )
        except RuntimeError as error:
            message = str(error)
            if "timeout" in message.lower():
                raise OcrTimeoutError("Tesseract OCR timed out.") from error
            raise OcrProcessingError("Tesseract OCR failed.", details={"error": message}) from error
        except Exception as error:
            raise OcrProcessingError("Tesseract OCR failed.", details={"error": str(error)}) from error

        words = _words_from_tesseract_data(data)
        full_text = " ".join(word.text for word in words)
        duration_ms = int((time.monotonic() - started_at) * 1000)
        logger.info(
            "ebook.ocr.completed",
            extra={
                "engine": self.engine_name,
                "languages": self.languages,
                "duration_ms": duration_ms,
                "word_count": len(words),
                "warning_count": len(warnings),
            },
        )
        return OcrResult(
            full_text=full_text,
            normalized_text=normalize_devanagari_digits(full_text),
            words=words,
            engine_name=self.engine_name,
            languages=self.languages,
            warnings=warnings,
        )

    def _load_pytesseract(self):
        try:
            import pytesseract
        except ImportError as error:
            raise OcrDependencyError("pytesseract is not installed.") from error
        return pytesseract


def preprocess_image(image, options):
    warnings = []
    processed_image = image
    if not isinstance(processed_image, Image.Image):
        raise OcrProcessingError("OCR input must be a PIL Image.")

    if options.get("grayscale", True):
        processed_image = ImageOps.grayscale(processed_image)

    if options.get("border_removal", False):
        processed_image = ImageOps.crop(processed_image, border=2)
        warnings.append("Safe border crop of 2 pixels was applied.")

    if options.get("threshold", True):
        threshold_value = int(options.get("threshold_value", 180))
        if processed_image.mode != "L":
            processed_image = ImageOps.grayscale(processed_image)
        processed_image = processed_image.point(
            lambda pixel: 255 if pixel > threshold_value else 0,
            mode="1",
        )

    if options.get("deskew", False):
        warnings.append("Deskew requested but not applied; no deskew backend is configured.")

    return processed_image, warnings


def _words_from_tesseract_data(data):
    words = []
    texts = data.get("text", [])
    for index, text in enumerate(texts):
        clean_text = (text or "").strip()
        if not clean_text:
            continue
        confidence = _parse_confidence(_value_at(data, "conf", index))
        words.append(
            OcrWord(
                text=clean_text,
                normalized_text=normalize_devanagari_digits(clean_text),
                confidence=confidence,
                left=_int_value(data, "left", index),
                top=_int_value(data, "top", index),
                width=_int_value(data, "width", index),
                height=_int_value(data, "height", index),
                block_num=_optional_int(data, "block_num", index),
                line_num=_optional_int(data, "line_num", index),
                par_num=_optional_int(data, "par_num", index),
                word_num=_optional_int(data, "word_num", index),
            )
        )
    return words


def _value_at(data, key, index):
    values = data.get(key, [])
    if index >= len(values):
        return None
    return values[index]


def _parse_confidence(value):
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0:
        return None
    return confidence


def _int_value(data, key, index):
    return int(_value_at(data, key, index) or 0)


def _optional_int(data, key, index):
    value = _value_at(data, key, index)
    if value in (None, ""):
        return None
    return int(value)
