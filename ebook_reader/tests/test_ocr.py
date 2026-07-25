import json
import tempfile
from io import BytesIO
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image
from pypdf import PdfWriter

from ebook_reader.models import EbookDocument
from ebook_reader.services.ocr.base import normalize_devanagari_digits
from ebook_reader.services.ocr.exceptions import OcrConfigurationError
from ebook_reader.services.ocr.factory import get_ocr_engine
from ebook_reader.services.ocr.tesseract_engine import TesseractOcrEngine, preprocess_image
from ebook_reader.services.pdf_rendering import render_pdf_page_to_image
from library.models import Book, Category


class FakePytesseract:
    class Output:
        DICT = "dict"

    def image_to_data(self, image, lang=None, output_type=None, timeout=None):
        return {
            "text": ["", "विषय", "सूची", "१२३"],
            "conf": ["-1", "92.5", "88", "80"],
            "left": [0, 10, 60, 100],
            "top": [0, 20, 20, 20],
            "width": [0, 40, 35, 25],
            "height": [0, 12, 12, 12],
            "block_num": [0, 1, 1, 1],
            "par_num": [0, 1, 1, 1],
            "line_num": [0, 1, 1, 1],
            "word_num": [0, 1, 2, 3],
        }


def blank_pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class OcrEngineTests(TestCase):
    def test_normalizes_devanagari_digits_without_changing_original_text(self):
        self.assertEqual(normalize_devanagari_digits("पृष्ठ १२३"), "पृष्ठ 123")

    def test_tesseract_engine_returns_structured_words(self):
        engine = TesseractOcrEngine(
            languages="hin+eng",
            timeout=5,
            preprocessing={"threshold": False},
            pytesseract_module=FakePytesseract(),
        )

        result = engine.extract(Image.new("RGB", (160, 80), "white"))

        self.assertEqual(result.engine_name, "tesseract")
        self.assertEqual(result.languages, "hin+eng")
        self.assertIn("विषय", result.full_text)
        self.assertIn("123", result.normalized_text)
        self.assertEqual(result.words[2].text, "१२३")
        self.assertEqual(result.words[2].normalized_text, "123")
        self.assertEqual(result.words[0].line_num, 1)

    def test_preprocessing_can_threshold_and_grayscale(self):
        image = Image.new("RGB", (20, 20), "white")

        processed, warnings = preprocess_image(
            image,
            {
                "grayscale": True,
                "threshold": True,
                "threshold_value": 180,
                "deskew": True,
                "border_removal": True,
            },
        )

        self.assertEqual(processed.mode, "1")
        self.assertTrue(any("Deskew requested" in warning for warning in warnings))
        self.assertTrue(any("border crop" in warning for warning in warnings))

    @override_settings(EBOOK_OCR_ENGINE="unknown")
    def test_factory_rejects_unknown_engine(self):
        with self.assertRaises(OcrConfigurationError):
            get_ocr_engine()


class PdfRenderingAndCommandTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_media = tempfile.TemporaryDirectory()
        cls.override_settings = override_settings(
            MEDIA_ROOT=cls.temp_media.name,
            EBOOK_RENDER_DPI=150,
            EBOOK_OCR_ENGINE="tesseract",
            EBOOK_OCR_LANGUAGES="hin+eng",
            EBOOK_OCR_TIMEOUT_SECONDS=5,
            EBOOK_OCR_PREPROCESSING={"grayscale": True, "threshold": False},
        )
        cls.override_settings.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.override_settings.disable()
        cls.temp_media.cleanup()

    def setUp(self):
        category = Category.objects.create(name="Vani")
        book = Book.objects.create(title="OCR Book", slug="ocr-book", category=category)
        book.pdf_file.save("ocr-book.pdf", ContentFile(blank_pdf_bytes()), save=True)
        self.document = EbookDocument.objects.create(book=book)

    def test_renders_pdf_page_to_pil_image(self):
        image = render_pdf_page_to_image(self.document, 1, dpi=150)

        self.assertIsInstance(image, Image.Image)
        self.assertGreater(image.width, 100)
        self.assertGreater(image.height, 100)

    @patch("ebook_reader.services.ocr.tesseract_engine.TesseractOcrEngine._load_pytesseract")
    def test_management_command_outputs_json(self, mocked_loader):
        mocked_loader.return_value = FakePytesseract()
        output = BytesIO()
        text_output = TextOutput(output)

        call_command("ocr_ebook_page", self.document.id, 1, stdout=text_output)

        data = json.loads(output.getvalue().decode())
        self.assertEqual(data["engine_name"], "tesseract")
        self.assertIn("123", data["normalized_text"])

    @patch("ebook_reader.services.ocr.tesseract_engine.TesseractOcrEngine._load_pytesseract")
    def test_management_command_outputs_text(self, mocked_loader):
        mocked_loader.return_value = FakePytesseract()
        output = BytesIO()
        text_output = TextOutput(output)

        call_command(
            "ocr_ebook_page",
            self.document.id,
            1,
            "--format",
            "text",
            stdout=text_output,
        )

        self.assertIn("विषय", output.getvalue().decode())

    @patch("ebook_reader.services.pdf_rendering.render_pdf_page_to_image")
    @patch("ebook_reader.services.ocr.tesseract_engine.TesseractOcrEngine._load_pytesseract")
    def test_toc_command_can_use_ocr_fallback(self, mocked_loader, mocked_render):
        mocked_loader.return_value = FakePytesseract()
        mocked_render.return_value = Image.new("RGB", (160, 80), "white")
        output = BytesIO()
        text_output = TextOutput(output)

        call_command("detect_ebook_toc", self.document.id, "--ocr", stdout=text_output)

        data = json.loads(output.getvalue().decode())
        self.assertEqual(data["strategy_name"], "ocr_toc")
        self.assertTrue(data["found"])


class TextOutput:
    def __init__(self, output):
        self.output = output

    def write(self, value):
        self.output.write(str(value).encode())
        self.output.write(b"\n")
