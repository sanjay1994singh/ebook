import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from ebook_reader.models import Book, BookPage, Highlight, IndexItem
from ebook_reader.utils import (
    PageLayoutResult,
    PdfOcrError,
    _render_pdf_page,
    extract_book_pages,
    is_garbled_text,
    ocr_pdf_page,
    ocr_pdf_page_layout,
    page_text_to_html,
)
from ebook_reader.tasks import process_uploaded_book


class TextExtractionTests(TestCase):
    def test_legacy_font_signatures_are_detected_without_flagging_english(self):
        self.assertTrue(is_garbled_text("AA Jh dqitfcgkjh ds fy, iz'u"))
        self.assertTrue(is_garbled_text("¼1/4Eikfnr foo"))
        self.assertTrue(is_garbled_text(""))
        self.assertFalse(is_garbled_text("A normal English paragraph about philosophy."))
        self.assertFalse(is_garbled_text("यह साफ़ हिन्दी यूनिकोड पाठ है।"))

    def test_page_text_is_normalized_wrapped_and_escaped(self):
        html = page_text_to_html("  पहली पंक्ति  \n\n<script>alert(1)</script>")
        self.assertEqual(
            html,
            '<p class="reader-line">पहली पंक्ति</p>\n'
            '<p class="reader-line">&lt;script&gt;alert(1)&lt;/script&gt;</p>',
        )

    @override_settings(EBOOK_READER_LEGACY_TEXT_CONVERTER="ebook_reader.tests.test_line_reader.uppercase")
    def test_configured_legacy_converter_is_used(self):
        self.assertEqual(page_text_to_html("legacy"), '<p class="reader-line">LEGACY</p>')

    @patch("ebook_reader.utils.PdfReader")
    def test_pdf_pages_are_bulk_replaced(self, reader_class):
        book = Book.objects.create(
            title="Extract me",
            pdf_file=SimpleUploadedFile("extract.pdf", b"fake pdf"),
        )
        BookPage.objects.create(book=book, page_number=99, content="old")
        first_page = Mock()
        first_page.extract_text.return_value = "line one\nline two"
        second_page = Mock()
        second_page.extract_text.return_value = "दूसरा पृष्ठ"
        reader_class.return_value.pages = [first_page, second_page]

        self.assertEqual(extract_book_pages(book), 2)
        self.assertEqual(list(book.pages.values_list("page_number", flat=True)), [1, 2])
        self.assertIn("line two", book.pages.get(page_number=1).content)
        book.refresh_from_db()
        self.assertEqual(book.processing_status, Book.ProcessingStatus.READY)
        self.assertEqual(book.total_pages, 2)
        self.assertEqual(book.processed_pages, 2)
        first_page = book.pages.get(page_number=1)
        self.assertEqual(first_page.line_count, 2)
        self.assertEqual(first_page.extraction_method, BookPage.ExtractionMethod.EMBEDDED)

    @patch("ebook_reader.utils.PdfReader")
    def test_reprocessing_preserves_page_id_and_highlights(self, reader_class):
        user = get_user_model().objects.create_user(username="preserved")
        book = Book.objects.create(
            title="Preserve annotations",
            pdf_file=SimpleUploadedFile("preserve.pdf", b"fake pdf"),
        )
        existing_page = BookPage.objects.create(
            book=book,
            page_number=1,
            content="old",
            plain_text="old",
        )
        highlight = Highlight.objects.create(
            user=user,
            page=existing_page,
            selected_text="old",
        )
        pdf_page = Mock()
        pdf_page.extract_text.return_value = "new Unicode text"
        reader_class.return_value.pages = [pdf_page]

        extract_book_pages(book)

        existing_page.refresh_from_db()
        highlight.refresh_from_db()
        self.assertEqual(existing_page.pk, highlight.page_id)
        self.assertEqual(existing_page.plain_text, "new Unicode text")

    @patch("ebook_reader.utils.ocr_pdf_page_layout")
    @patch("ebook_reader.utils.PdfReader")
    def test_garbled_and_empty_pages_use_line_preserving_ocr(self, reader_class, ocr_page):
        book = Book.objects.create(
            title="OCR me",
            pdf_file=SimpleUploadedFile("ocr.pdf", b"fake pdf"),
        )
        garbled_page = Mock()
        garbled_page.extract_text.return_value = "AA Jh dqitfcgkjh ds fy, iz'u"
        empty_page = Mock()
        empty_page.extract_text.return_value = ""
        reader_class.return_value.pages = [garbled_page, empty_page]
        ocr_page.side_effect = [
            PageLayoutResult(
                "पहली पंक्ति\nदूसरी पंक्ति",
                '<p class="reader-line">पहली पंक्ति</p>\n<p class="reader-line">दूसरी पंक्ति</p>',
                2,
            ),
            PageLayoutResult(
                "English heading\nहिन्दी पाठ",
                '<p class="reader-line">English heading</p>\n<p class="reader-line">हिन्दी पाठ</p>',
                2,
            ),
        ]

        self.assertEqual(extract_book_pages(book), 2)
        self.assertEqual([call.args[1] for call in ocr_page.call_args_list], [1, 2])
        first_html = book.pages.get(page_number=1).content
        self.assertIn('<p class="reader-line">पहली पंक्ति</p>', first_html)
        self.assertIn('<p class="reader-line">दूसरी पंक्ति</p>', first_html)
        self.assertEqual(
            book.pages.get(page_number=1).extraction_method,
            BookPage.ExtractionMethod.OCR,
        )

    @patch("ebook_reader.utils.ocr_pdf_page_layout", side_effect=PdfOcrError("not installed"))
    @patch("ebook_reader.utils.PdfReader")
    def test_missing_tesseract_keeps_best_available_text(self, reader_class, _ocr_page):
        book = Book.objects.create(
            title="Fallback",
            pdf_file=SimpleUploadedFile("fallback.pdf", b"fake pdf"),
        )
        page = Mock()
        page.extract_text.return_value = "AA Jh dqitfcgkjh ds fy, iz'u"
        reader_class.return_value.pages = [page]

        self.assertEqual(extract_book_pages(book), 1)
        self.assertIn("dqitfcgkjh", book.pages.get().content)
        self.assertEqual(
            book.pages.get().extraction_method,
            BookPage.ExtractionMethod.FALLBACK,
        )

    @override_settings(
        EBOOK_OCR_LANGUAGES="hin+eng",
        EBOOK_OCR_TESSERACT_CONFIG="--psm 6",
        EBOOK_OCR_TIMEOUT_SECONDS=30,
    )
    @patch("pytesseract.image_to_string", return_value="हिन्दी\nEnglish")
    @patch("ebook_reader.utils._prepare_ocr_image")
    @patch("ebook_reader.utils._render_pdf_page")
    def test_tesseract_uses_hindi_and_english(
        self,
        render_page,
        prepare_image,
        image_to_string,
    ):
        render_page.return_value = Mock()
        prepare_image.return_value = Mock()
        self.assertEqual(ocr_pdf_page(b"pdf", 1), "हिन्दी\nEnglish")
        image_to_string.assert_called_once_with(
            prepare_image.return_value,
            lang="hin+eng",
            config="--psm 6",
            timeout=30,
        )

    @override_settings(
        EBOOK_OCR_LANGUAGES="hin+eng",
        EBOOK_OCR_TESSERACT_CONFIG="--psm 3",
        EBOOK_OCR_TIMEOUT_SECONDS=30,
    )
    @patch("ebook_reader.utils._apply_pdf_style_hints")
    @patch("pytesseract.image_to_data")
    @patch("ebook_reader.utils._prepare_ocr_image")
    @patch("ebook_reader.utils._render_pdf_page")
    def test_layout_ocr_preserves_header_number_size_weight_and_order(
        self,
        render_page,
        prepare_image,
        image_to_data,
        _style_hints,
    ):
        from PIL import Image

        render_page.return_value = Image.new("RGB", (600, 840), "white")
        prepare_image.return_value = render_page.return_value
        image_to_data.return_value = {
            "text": ["शीर्षक", "9", "मुख्य", "पाठ", "सीमा-जंक"],
            "conf": [95, 93, 96, 96, 20],
            "left": [180, 530, 210, 300, 40],
            "top": [40, 40, 180, 180, 720],
            "width": [230, 15, 80, 55, 520],
            "height": [30, 25, 52, 52, 20],
            "block_num": [1, 1, 3, 3, 4],
            "par_num": [1, 1, 1, 1, 1],
            "line_num": [1, 1, 1, 1, 1],
            "word_num": [1, 2, 1, 2, 1],
        }

        result = ocr_pdf_page_layout(b"pdf", 1)

        self.assertEqual(result.plain_text.splitlines()[0], "शीर्षक    9")
        self.assertEqual(result.plain_text.splitlines()[1], "मुख्य पाठ")
        self.assertIn("reader-layout-row", result.html)
        self.assertIn("reader-bold", result.html)
        self.assertNotIn("सीमा-जंक", result.plain_text)
        prepare_image.assert_called_once_with(render_page.return_value, crop_margins=False)

    @patch("ebook_reader.utils._render_with_pdf2image")
    @patch("ebook_reader.utils._render_with_pymupdf", side_effect=PdfOcrError("no PyMuPDF"))
    def test_rendering_falls_back_from_pymupdf_to_pdf2image(self, _pymupdf, pdf2image):
        expected = Mock()
        pdf2image.return_value = expected
        self.assertIs(_render_pdf_page(b"pdf", 1), expected)


def uppercase(value):
    return value.upper()


class ReaderViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.book = Book.objects.create(
            title="ज्ञान ग्रंथ",
            author="विद्वान",
            pdf_file=SimpleUploadedFile("book.pdf", b"not-read-during-test"),
        )
        cls.page = BookPage.objects.create(
            book=cls.book,
            page_number=1,
            content='<p class="reader-line">परीक्षण</p>',
        )
        cls.index_item = IndexItem.objects.create(
            book=cls.book,
            title="प्रथम पाठ",
            start_page=1,
            end_page=1,
        )
        cls.user = get_user_model().objects.create_user(username="reader", password="secret")

    def test_index_range_validation(self):
        item = IndexItem(book=self.book, title="Invalid", start_page=3, end_page=2)
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_book_list_and_reader_render(self):
        listing = self.client.get(reverse("ebook_reader:book_list"))
        reader = self.client.get(reverse("ebook_reader:reader", args=[self.book.pk]))
        self.assertContains(listing, self.book.title)
        self.assertContains(reader, self.index_item.title)
        self.assertContains(reader, "परीक्षण")
        self.assertContains(reader, 'id="page-1"')

    def test_highlight_requires_login(self):
        response = self.client.post(
            reverse("ebook_reader:save_highlight"),
            data=json.dumps({"page_id": self.page.pk, "selected_text": "परीक्षण"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Highlight.objects.count(), 0)

    def test_authenticated_user_can_save_highlight(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("ebook_reader:save_highlight"),
            data=json.dumps(
                {"page_id": self.page.pk, "selected_text": "परीक्षण", "color": "yellow"}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        highlight = Highlight.objects.get()
        self.assertEqual(highlight.user, self.user)
        self.assertEqual(highlight.page, self.page)


class ScalableIngestionTests(TestCase):
    @patch("ebook_reader.tasks.extract_book_pages", return_value=12)
    def test_celery_task_claims_and_processes_book(self, extract_pages):
        book = Book.objects.create(
            title="Queued",
            pdf_file=SimpleUploadedFile("queued.pdf", b"pdf"),
        )
        result = process_uploaded_book.apply(args=[book.pk]).get()
        self.assertEqual(result["status"], "ready")
        extract_pages.assert_called_once_with(book, force_ocr=None)

    def test_celery_task_skips_duplicate_processing(self):
        book = Book.objects.create(
            title="Already running",
            pdf_file=SimpleUploadedFile("running.pdf", b"pdf"),
            processing_status=Book.ProcessingStatus.PROCESSING,
        )
        result = process_uploaded_book.apply(args=[book.pk]).get()
        self.assertEqual(result["status"], "skipped")

    @patch("ebook_reader.management.commands.import_line_ebooks.process_uploaded_book.delay")
    def test_folder_import_queues_each_pdf(self, delay):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as media_dir:
            Path(source_dir, "First Book.pdf").write_bytes(b"%PDF fixture")
            Path(source_dir, "ignore.txt").write_text("not a pdf", encoding="utf-8")
            output = StringIO()
            with override_settings(MEDIA_ROOT=media_dir):
                call_command("import_line_ebooks", source_dir, stdout=output)

        book = Book.objects.get(title="First Book")
        delay.assert_called_once_with(book.pk, force_ocr=False)
        self.assertIn("imported=1", output.getvalue())
