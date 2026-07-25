import json
import tempfile
from io import StringIO
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from ebook_reader.models import EbookDocument
from ebook_reader.services.onboarding import OnboardingOptions, onboard_ebooks
from ebook_reader.tests.test_pdf_metadata import blank_pdf_bytes
from library.models import Book, Category


class EbookOnboardingTests(TestCase):
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

    def create_book(self, title="Book", *, with_pdf=True, is_published=True):
        index = Book.objects.count() + 1
        book = Book.objects.create(
            title=f"{title} {index}",
            slug=f"{title.lower().replace(' ', '-')}-{index}",
            category=self.category,
            is_published=is_published,
            pdf_import_status="not_extracted",
        )
        if with_pdf:
            book.pdf_file.save(f"book-{index}.pdf", ContentFile(blank_pdf_bytes()), save=True)
        return book

    def test_book_with_pdf_creates_ebook_document(self):
        book = self.create_book()

        summary = onboard_ebooks(OnboardingOptions(book_ids=[book.id]))

        self.assertEqual(summary.created, 1)
        document = EbookDocument.objects.get(book=book)
        self.assertEqual(document.toc_mode, EbookDocument.TocMode.AUTO)
        self.assertEqual(document.status, EbookDocument.Status.PENDING)

    def test_book_without_pdf_is_skipped(self):
        book = self.create_book(with_pdf=False)

        summary = onboard_ebooks(OnboardingOptions(book_ids=[book.id]))

        self.assertEqual(summary.missing_pdf, 1)
        self.assertFalse(EbookDocument.objects.filter(book=book).exists())

    def test_existing_document_is_not_duplicated(self):
        book = self.create_book()
        EbookDocument.objects.create(book=book)

        summary = onboard_ebooks(OnboardingOptions(book_ids=[book.id]))

        self.assertEqual(summary.created, 0)
        self.assertEqual(summary.already_existed, 1)
        self.assertEqual(EbookDocument.objects.filter(book=book).count(), 1)

    def test_dry_run_creates_nothing(self):
        book = self.create_book()

        summary = onboard_ebooks(OnboardingOptions(book_ids=[book.id], dry_run=True))

        self.assertEqual(summary.eligible, 1)
        self.assertEqual(summary.created, 0)
        self.assertFalse(EbookDocument.objects.filter(book=book).exists())

    def test_repeated_run_is_idempotent(self):
        book = self.create_book()

        first = onboard_ebooks(OnboardingOptions(book_ids=[book.id]))
        second = onboard_ebooks(OnboardingOptions(book_ids=[book.id]))

        self.assertEqual(first.created, 1)
        self.assertEqual(second.already_existed, 1)
        self.assertEqual(EbookDocument.objects.filter(book=book).count(), 1)

    def test_batch_size_is_respected(self):
        for index in range(3):
            self.create_book(title=f"Batch {index}")

        summary = onboard_ebooks(OnboardingOptions(all_with_pdf=True, batch_size=2))

        self.assertEqual(summary.examined, 2)
        self.assertEqual(EbookDocument.objects.count(), 2)

    @patch("ebook_reader.services.onboarding.detect_ebook_toc_document.delay")
    @patch("ebook_reader.services.onboarding.inspect_ebook_document.delay")
    def test_queue_options_are_called(self, inspect_delay, toc_delay):
        book = self.create_book()

        summary = onboard_ebooks(
            OnboardingOptions(
                book_ids=[book.id],
                queue_inspection=True,
                queue_toc_detection=True,
            )
        )

        document = EbookDocument.objects.get(book=book)
        inspect_delay.assert_called_once_with(document.id)
        toc_delay.assert_called_once_with(document.id)
        self.assertEqual(summary.queued_for_inspection, 1)
        self.assertEqual(summary.queued_for_toc_detection, 1)

    def test_existing_book_is_unchanged(self):
        book = self.create_book(is_published=False)
        original_pdf_name = book.pdf_file.name
        original_updated_at = book.updated_at

        onboard_ebooks(OnboardingOptions(book_ids=[book.id]))

        book.refresh_from_db()
        self.assertEqual(book.pdf_file.name, original_pdf_name)
        self.assertEqual(book.is_published, False)
        self.assertEqual(book.updated_at, original_updated_at)

    def test_different_books_keep_independent_toc_configuration(self):
        first = self.create_book(title="First")
        second = self.create_book(title="Second")

        onboard_ebooks(OnboardingOptions(book_ids=[first.id, second.id]))

        first_document = EbookDocument.objects.get(book=first)
        second_document = EbookDocument.objects.get(book=second)
        first_document.toc_mode = EbookDocument.TocMode.MANUAL
        first_document.toc_start_page = 9
        first_document.toc_end_page = 13
        first_document.total_pdf_pages = 30
        first_document.save()

        second_document.refresh_from_db()
        self.assertEqual(second_document.toc_mode, EbookDocument.TocMode.AUTO)
        self.assertIsNone(second_document.toc_start_page)

    def test_failure_in_one_book_does_not_abort_batch(self):
        good_book = self.create_book(title="Good")
        bad_book = self.create_book(title="Bad")

        with patch(
            "ebook_reader.services.onboarding.create_ebook_document_for_book",
            side_effect=[Exception("broken"), (None, False)],
        ):
            summary = onboard_ebooks(
                OnboardingOptions(book_ids=[bad_book.id, good_book.id], batch_size=10)
            )

        self.assertEqual(summary.examined, 2)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(len(summary.failure_details), 1)

    def test_management_command_outputs_structured_summary(self):
        book = self.create_book()
        output = StringIO()

        call_command("onboard_ebooks", "--book-id", str(book.id), stdout=output)

        data = json.loads(output.getvalue())
        self.assertEqual(data["examined"], 1)
        self.assertEqual(data["created"], 1)
