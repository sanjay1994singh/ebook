import json
import tempfile
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from ebook_reader.models import EbookDocument
from ebook_reader.services.toc_detection import detect_ebook_toc
from ebook_reader.services.toc_detection.admin_workflow import (
    accept_detected_toc_range,
    run_toc_detection,
)
from ebook_reader.services.toc_detection.strategies import OcrTocStrategy
from library.models import Book, Category


def pdf_with_text_bytes(page_texts):
    writer = PdfWriter()
    for text in page_texts:
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        safe_text = text.encode("ascii", errors="ignore").decode("ascii")
        stream.set_data(f"BT /F1 12 Tf 72 72 Td ({safe_text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = stream
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def toc_page(label="Contents"):
    return "\n".join(
        [
            label,
            "1 First lesson 10",
            "2 Second lesson 20",
            "3 Third lesson 30",
        ]
    )


class TocDetectionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_media = tempfile.TemporaryDirectory()
        cls.override_settings = override_settings(
            MEDIA_ROOT=cls.temp_media.name,
            EBOOK_READER_TOC_SCAN_PAGE_LIMIT=40,
        )
        cls.override_settings.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.override_settings.disable()
        cls.temp_media.cleanup()

    def setUp(self):
        self.category = Category.objects.create(name="Vani")

    def create_document(self, page_texts, **document_fields):
        book = Book.objects.create(
            title=f"TOC Book {Book.objects.count() + 1}",
            slug=f"toc-book-{Book.objects.count() + 1}",
            category=self.category,
        )
        book.pdf_file.save("toc-book.pdf", ContentFile(pdf_with_text_bytes(page_texts)), save=True)
        return EbookDocument.objects.create(book=book, **document_fields)

    def test_pdf_with_toc_on_pages_2_to_3(self):
        document = self.create_document(["Cover", toc_page(), toc_page(), "Chapter"])

        result = detect_ebook_toc(document)

        self.assertEqual(result["strategy_name"], "embedded_text_toc")
        self.assertEqual(result["detected_start_page"], 2)
        self.assertEqual(result["detected_end_page"], 3)

    def test_sample_pdf_can_be_configured_manually_as_pages_9_to_13(self):
        document = self.create_document(
            ["Page"] * 20,
            toc_mode=EbookDocument.TocMode.MANUAL,
            toc_start_page=9,
            toc_end_page=13,
            total_pdf_pages=20,
        )

        result = detect_ebook_toc(document)

        self.assertEqual(result["strategy_name"], "manual_range")
        self.assertEqual(result["detected_start_page"], 9)
        self.assertEqual(result["detected_end_page"], 13)

    def test_pdf_with_single_toc_page(self):
        document = self.create_document(["Cover", toc_page(), "Chapter"])

        result = detect_ebook_toc(document)

        self.assertEqual(result["detected_start_page"], 2)
        self.assertEqual(result["detected_end_page"], 2)

    def test_pdf_with_no_toc_does_not_guess(self):
        document = self.create_document(["Cover", "Preface", "Chapter"])

        result = detect_ebook_toc(document)

        self.assertFalse(result["found"])
        self.assertTrue(result["requires_manual_configuration"])
        self.assertIsNone(result["detected_start_page"])

    def test_garbled_embedded_text_falls_back_to_ocr(self):
        document = self.create_document(["????", "????", "????"])

        def fake_ocr(_reader, page_index):
            if page_index == 1:
                return toc_page("\u0935\u093f\u0937\u092f \u0938\u0942\u091a\u0940")
            return ""

        result = detect_ebook_toc(document, ocr_text_provider=fake_ocr)

        self.assertEqual(result["strategy_name"], "ocr_toc")
        self.assertEqual(result["detected_start_page"], 2)
        self.assertEqual(result["detected_end_page"], 2)

    def test_manual_range_takes_priority_over_detected_range(self):
        document = self.create_document(
            ["Cover", toc_page(), "Chapter"],
            toc_mode=EbookDocument.TocMode.MANUAL,
            toc_start_page=9,
            toc_end_page=13,
            total_pdf_pages=20,
        )

        result = detect_ebook_toc(document)

        self.assertEqual(result["strategy_name"], "manual_range")
        self.assertEqual(result["detected_start_page"], 9)
        self.assertEqual(result["detected_end_page"], 13)

    def test_invalid_page_ranges_are_rejected(self):
        document = EbookDocument(
            toc_mode=EbookDocument.TocMode.MANUAL,
            toc_start_page=13,
            toc_end_page=9,
            total_pdf_pages=20,
        )

        with self.assertRaises(ValidationError):
            document.full_clean()

    def test_page_ranges_are_validated_against_total_pdf_pages(self):
        document = EbookDocument(
            toc_mode=EbookDocument.TocMode.MANUAL,
            toc_start_page=9,
            toc_end_page=21,
            total_pdf_pages=20,
        )

        with self.assertRaises(ValidationError):
            document.full_clean()

    def test_detection_does_not_scan_beyond_configured_limit(self):
        document = self.create_document(
            ["Cover", "Preface", toc_page()],
            toc_scan_page_limit=2,
        )

        result = detect_ebook_toc(document)

        self.assertFalse(result["found"])
        self.assertEqual(result["scan_limit_pages"], 2)

    def test_run_detection_stores_detected_fields_separately(self):
        document = self.create_document(["Cover", toc_page(), "Chapter"])

        result = run_toc_detection(EbookDocument.objects.filter(id=document.id))

        document.refresh_from_db()
        self.assertEqual(result.detected, 1)
        self.assertEqual(document.toc_mode, EbookDocument.TocMode.AUTO)
        self.assertIsNone(document.toc_start_page)
        self.assertIsNone(document.toc_end_page)
        self.assertEqual(document.detected_toc_start_page, 2)
        self.assertEqual(document.detected_toc_end_page, 2)
        self.assertGreater(document.toc_detection_confidence, 0)
        self.assertEqual(document.status, EbookDocument.Status.REVIEW_REQUIRED)

    def test_accept_detected_range_switches_to_manual_without_guessing(self):
        document = self.create_document(["Cover", toc_page(), "Chapter"])
        run_toc_detection(EbookDocument.objects.filter(id=document.id))

        result = accept_detected_toc_range(EbookDocument.objects.filter(id=document.id))

        document.refresh_from_db()
        self.assertEqual(result.updated, 1)
        self.assertEqual(document.toc_mode, EbookDocument.TocMode.MANUAL)
        self.assertEqual(document.toc_start_page, 2)
        self.assertEqual(document.toc_end_page, 2)

    def test_mode_none_skips_detection(self):
        document = self.create_document(
            ["Cover", toc_page(), "Chapter"],
            toc_mode=EbookDocument.TocMode.NONE,
        )

        result = detect_ebook_toc(document)

        self.assertEqual(result["strategy_name"], "none")
        self.assertEqual(result["scan_limit_pages"], 0)
        self.assertFalse(result["requires_manual_configuration"])

    def test_management_command_prints_structured_json(self):
        document = self.create_document(["Cover", toc_page(), "Chapter"])
        output = BytesIO()
        text_output = TextOutput(output)

        call_command("detect_ebook_toc", document.id, stdout=text_output)

        data = json.loads(output.getvalue().decode())
        self.assertEqual(data["strategy_name"], "embedded_text_toc")
        self.assertEqual(data["detected_start_page"], 2)

    def test_ocr_strategy_can_detect_hindi_indicator_directly(self):
        document = self.create_document(["????"])
        _pdf_file, reader = __import__(
            "ebook_reader.services.pdf_metadata",
            fromlist=["open_pdf_reader"],
        ).open_pdf_reader(document)

        strategy = OcrTocStrategy(
            ocr_text_provider=lambda _reader, _page_index: (
                "\u0935\u093f\u0937\u092f \u0938\u0942\u091a\u0940\n1 Test 10\n2 Test 20\n3 Test 30"
            )
        )
        result = strategy.detect(reader, document, max_pages=1)

        self.assertTrue(result.found)
        self.assertEqual(result.detected_start_page, 1)


class TextOutput:
    def __init__(self, output):
        self.output = output

    def write(self, value):
        self.output.write(str(value).encode())
        self.output.write(b"\n")
