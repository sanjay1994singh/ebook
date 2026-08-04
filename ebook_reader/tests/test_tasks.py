import tempfile

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from ebook_reader.models import EbookDocument, EbookLesson
from ebook_reader.tasks import inspect_ebook_document
from ebook_reader.tests.test_pdf_metadata import blank_pdf_bytes, text_pdf_bytes
from library.models import Book, Category


class EbookInspectionTaskTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_media = tempfile.TemporaryDirectory()
        cls.override_settings = override_settings(
            MEDIA_ROOT=cls.temp_media.name,
            CELERY_TASK_ALWAYS_EAGER=True,
            CELERY_TASK_EAGER_PROPAGATES=True,
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

    def create_document(self, pdf_bytes=None, status=EbookDocument.Status.PENDING):
        book = Book.objects.create(
            title=f"Task Book {Book.objects.count() + 1}",
            slug=f"task-book-{Book.objects.count() + 1}",
            category=self.category,
        )
        if pdf_bytes is not None:
            book.pdf_file.save("task-book.pdf", ContentFile(pdf_bytes), save=True)
        return EbookDocument.objects.create(book=book, status=status)

    def test_task_stores_metadata_and_sets_review_required_for_text_pdf(self):
        document = self.create_document(pdf_bytes=text_pdf_bytes())

        result = inspect_ebook_document.apply(args=[document.id]).get()

        document.refresh_from_db()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(document.status, EbookDocument.Status.REVIEW_REQUIRED)
        self.assertEqual(document.total_pdf_pages, 1)
        self.assertTrue(document.processing_metadata["has_embedded_text"])
        self.assertEqual(document.processing_error, "")

    def test_task_sets_pending_for_pdf_without_text_or_bookmarks(self):
        document = self.create_document(pdf_bytes=blank_pdf_bytes())

        inspect_ebook_document.apply(args=[document.id]).get()

        document.refresh_from_db()
        self.assertEqual(document.status, EbookDocument.Status.PENDING)
        self.assertEqual(document.total_pdf_pages, 1)

    def test_task_failure_sets_failed_with_safe_error(self):
        document = self.create_document(pdf_bytes=b"invalid pdf")

        result = inspect_ebook_document.apply(args=[document.id]).get()

        document.refresh_from_db()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(document.status, EbookDocument.Status.FAILED)
        self.assertIn("corrupt_pdf", document.processing_error)

    def test_processing_document_is_skipped_to_avoid_duplicate_work(self):
        document = self.create_document(
            pdf_bytes=text_pdf_bytes(),
            status=EbookDocument.Status.PROCESSING,
        )

        result = inspect_ebook_document.apply(args=[document.id]).get()

        document.refresh_from_db()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(document.status, EbookDocument.Status.PROCESSING)
        self.assertIsNone(document.total_pdf_pages)

    def test_task_is_idempotent_and_does_not_modify_lessons(self):
        document = self.create_document(pdf_bytes=text_pdf_bytes())
        EbookLesson.objects.create(
            ebook=document,
            order=1,
            title="Manual lesson",
            start_page=1,
            is_verified=True,
        )

        inspect_ebook_document.apply(args=[document.id]).get()
        inspect_ebook_document.apply(args=[document.id]).get()

        document.refresh_from_db()
        self.assertEqual(document.status, EbookDocument.Status.REVIEW_REQUIRED)
        self.assertEqual(document.total_pdf_pages, 1)
        self.assertEqual(document.lessons.count(), 1)
