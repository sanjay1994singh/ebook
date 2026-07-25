import json
import tempfile
from io import BytesIO
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from pypdf import PdfWriter

from ebook_reader.models import (
    EbookDocument,
    EbookLesson,
    EbookProcessingRun,
    EbookTocCandidate,
)
from ebook_reader.services.toc_parser.models import TocPageInput
from ebook_reader.services.toc_processing import process_ebook_toc
from library.models import Book, Category


def blank_pdf_bytes(page_count=5):
    writer = PdfWriter()
    for _index in range(page_count):
        writer.add_blank_page(width=300, height=300)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def page(number, text):
    return TocPageInput(page_number=number, embedded_text=text)


class TocProcessingTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_media = tempfile.TemporaryDirectory()
        cls.override_settings = override_settings(MEDIA_ROOT=cls.temp_media.name)
        cls.override_settings.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.override_settings.disable()
        cls.temp_media.cleanup()

    def setUp(self):
        self.category = Category.objects.create(name="Vani")

    def create_document(self, *, toc_start=2, toc_end=2, total_pages=10, offset=0):
        book = Book.objects.create(
            title=f"Process Book {Book.objects.count() + 1}",
            slug=f"process-book-{Book.objects.count() + 1}",
            category=self.category,
        )
        book.pdf_file.save(
            "process.pdf",
            ContentFile(blank_pdf_bytes(total_pages)),
            save=True,
        )
        return EbookDocument.objects.create(
            book=book,
            toc_mode=EbookDocument.TocMode.MANUAL,
            toc_start_page=toc_start,
            toc_end_page=toc_end,
            total_pdf_pages=total_pages,
            page_mapping_mode=EbookDocument.PageMappingMode.MANUAL_OFFSET,
            page_number_offset=offset,
        )

    def process_with_pages(self, document, pages, **kwargs):
        with patch(
            "ebook_reader.services.toc_processing._extract_toc_pages",
            return_value=(pages, []),
        ):
            return process_ebook_toc(document.id, **kwargs)

    def test_first_processing_run_creates_draft_lessons(self):
        document = self.create_document(total_pages=100, offset=1)

        result = self.process_with_pages(
            document,
            [page(2, "1 First lesson 10\n2 Second lesson 20")],
        )

        self.assertEqual(result.created_lessons, 2)
        self.assertEqual(EbookLesson.objects.count(), 2)
        first = EbookLesson.objects.order_by("order").first()
        self.assertEqual(first.title, "First lesson")
        self.assertEqual(first.printed_page_number, 10)
        self.assertEqual(first.start_page, 11)
        self.assertFalse(first.is_verified)
        document.refresh_from_db()
        self.assertEqual(document.status, EbookDocument.Status.REVIEW_REQUIRED)

    def test_identical_rerun_is_idempotent(self):
        document = self.create_document()
        pages = [page(2, "1 First lesson 10\n2 Second lesson 20")]

        self.process_with_pages(document, pages)
        self.process_with_pages(document, pages)

        self.assertEqual(EbookLesson.objects.count(), 2)
        self.assertEqual(EbookProcessingRun.objects.count(), 2)

    def test_verified_lessons_are_protected(self):
        document = self.create_document()
        EbookLesson.objects.create(
            ebook=document,
            order=1,
            title="Verified",
            start_page=5,
            is_verified=True,
        )

        result = self.process_with_pages(document, [page(2, "1 New lesson 10")])

        self.assertEqual(result.created_lessons, 0)
        self.assertEqual(result.skipped_lessons, 1)
        self.assertEqual(EbookLesson.objects.get().title, "Verified")

    def test_manually_edited_lessons_are_protected(self):
        document = self.create_document()
        EbookLesson.objects.create(
            ebook=document,
            order=1,
            title="Manual",
            start_page=5,
            is_manually_edited=True,
        )

        result = self.process_with_pages(document, [page(2, "1 New lesson 10")])

        self.assertEqual(result.created_lessons, 0)
        self.assertEqual(EbookLesson.objects.get().title, "Manual")

    def test_force_replacement_preserves_audit_snapshot(self):
        document = self.create_document()
        EbookLesson.objects.create(
            ebook=document,
            order=1,
            title="Verified",
            start_page=5,
            is_verified=True,
        )

        result = self.process_with_pages(
            document,
            [page(2, "1 New lesson 10")],
            force=True,
        )

        self.assertEqual(result.created_lessons, 1)
        self.assertEqual(EbookLesson.objects.get().title, "New lesson")
        run = EbookProcessingRun.objects.latest("id")
        self.assertIn("force_audit_snapshot", run.diagnostics)

    def test_partial_parser_failures_are_stored_as_review_candidates(self):
        document = self.create_document()

        result = self.process_with_pages(
            document,
            [page(2, "1 First 10\n1 Duplicate 20\nOnly heading")],
        )

        self.assertEqual(result.invalid_count, 2)
        self.assertGreaterEqual(EbookTocCandidate.objects.count(), 2)
        self.assertEqual(
            EbookTocCandidate.objects.filter(
                candidate_type=EbookTocCandidate.CandidateType.INVALID
            ).count(),
            2,
        )

    def test_no_accepted_toc_range_does_not_parse(self):
        document = self.create_document()
        document.toc_mode = EbookDocument.TocMode.AUTO
        document.toc_start_page = None
        document.toc_end_page = None
        document.save()

        result = process_ebook_toc(document.id)

        self.assertEqual(result.status, "review_required")
        self.assertEqual(EbookLesson.objects.count(), 0)

    def test_toc_mode_none_skips_processing(self):
        document = self.create_document()
        document.toc_mode = EbookDocument.TocMode.NONE
        document.save()

        result = process_ebook_toc(document.id)

        self.assertEqual(result.status, "skipped")
        self.assertEqual(EbookLesson.objects.count(), 0)

    def test_invalid_mapped_pages_are_kept_as_draft_with_warning(self):
        document = self.create_document(total_pages=20, offset=50)

        result = self.process_with_pages(document, [page(2, "1 Far lesson 10")])

        lesson = EbookLesson.objects.get()
        self.assertIsNone(lesson.start_page)
        self.assertTrue(any("outside" in warning for warning in lesson.warnings))
        self.assertEqual(result.created_lessons, 1)

    def test_concurrent_processing_protection(self):
        document = self.create_document()
        document.status = EbookDocument.Status.PROCESSING
        document.save()

        result = process_ebook_toc(document.id)

        self.assertEqual(result.status, "skipped")
        self.assertEqual(EbookProcessingRun.objects.count(), 0)

    def test_dry_run_changes_nothing(self):
        document = self.create_document()

        result = self.process_with_pages(
            document,
            [page(2, "1 First lesson 10")],
            dry_run=True,
        )

        self.assertEqual(result.status, "dry_run")
        self.assertEqual(EbookLesson.objects.count(), 0)
        self.assertEqual(EbookProcessingRun.objects.count(), 0)
        document.refresh_from_db()
        self.assertEqual(document.status, EbookDocument.Status.PENDING)

    def test_one_page_toc(self):
        document = self.create_document(toc_start=4, toc_end=4)

        result = self.process_with_pages(document, [page(4, "1 Only lesson 12")])

        self.assertEqual(result.created_lessons, 1)
        self.assertEqual(EbookLesson.objects.get().source_toc_page, 4)

    def test_multi_page_toc(self):
        document = self.create_document(toc_start=5, toc_end=6)

        result = self.process_with_pages(
            document,
            [page(5, "1 First 10"), page(6, "2 Second 20")],
        )

        self.assertEqual(result.created_lessons, 2)
        self.assertEqual(list(EbookLesson.objects.values_list("order", flat=True)), [1, 2])

    def test_tocs_can_be_at_different_ranges(self):
        first = self.create_document(toc_start=2, toc_end=2)
        second = self.create_document(toc_start=9, toc_end=10)

        self.process_with_pages(first, [page(2, "1 First 10")])
        self.process_with_pages(second, [page(9, "1 Other 20"), page(10, "2 More 30")])

        self.assertEqual(first.lessons.count(), 1)
        self.assertEqual(second.lessons.count(), 2)

    def test_missing_pdf_fails_as_technical_failure(self):
        book = Book.objects.create(
            title="No PDF",
            slug="no-pdf",
            category=self.category,
        )
        document = EbookDocument.objects.create(
            book=book,
            toc_mode=EbookDocument.TocMode.MANUAL,
            toc_start_page=1,
            toc_end_page=1,
        )

        result = process_ebook_toc(document.id)

        self.assertEqual(result.status, "failed")
        document.refresh_from_db()
        self.assertEqual(document.status, EbookDocument.Status.FAILED)

    def test_management_command_outputs_json(self):
        document = self.create_document()
        output = BytesIO()
        text_output = TextOutput(output)

        with patch(
            "ebook_reader.services.toc_processing._extract_toc_pages",
            return_value=([page(2, "1 First lesson 10")], []),
        ):
            call_command(
                "process_ebook_toc",
                document.id,
                "--show-diagnostics",
                stdout=text_output,
            )

        data = json.loads(output.getvalue().decode())
        self.assertEqual(data["created_lessons"], 1)
        self.assertIn("diagnostics", data)


class TextOutput:
    def __init__(self, output):
        self.output = output

    def write(self, value):
        self.output.write(str(value).encode())
        self.output.write(b"\n")
