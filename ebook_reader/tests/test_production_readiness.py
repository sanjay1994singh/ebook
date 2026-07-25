import tempfile

from django.contrib.auth import get_user_model
from django.core.checks import Error, Warning
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from ebook_reader.checks import ebook_reader_production_checks
from ebook_reader.models import EbookDocument, EbookLesson
from ebook_reader.services.feature_flags import (
    is_mobile_reader_available,
    is_web_reader_available,
)
from ebook_reader.tasks import inspect_ebook_document
from library.models import Book, BookPage, Category, Chapter


class EbookProductionReadinessTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_media = tempfile.TemporaryDirectory()
        cls.override_media = override_settings(MEDIA_ROOT=cls.temp_media.name)
        cls.override_media.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.override_media.disable()
        cls.temp_media.cleanup()

    def setUp(self):
        self.client = APIClient()
        self.category = Category.objects.create(name="Vani", slug="vani")
        self.staff = get_user_model().objects.create_superuser(
            username="staff",
            email="staff@example.com",
            password="pass",
        )

    def create_ebook(self, **fields):
        book = Book.objects.create(
            title="Readiness Book",
            slug=f"readiness-book-{Book.objects.count()}",
            category=self.category,
            is_published=True,
        )
        book.pdf_file.save("readiness.pdf", ContentFile(b"%PDF-1.4\n%%EOF"), save=True)
        ebook = EbookDocument.objects.create(
            book=book,
            status=fields.pop("status", EbookDocument.Status.READY),
            total_pdf_pages=10,
            page_mapping_status=EbookDocument.PageMappingStatus.ACCEPTED,
            **{
                "new_ebook_reader_enabled": True,
                "new_ebook_reader_web_enabled": True,
                "new_ebook_reader_mobile_enabled": True,
                **fields,
            },
        )
        EbookLesson.objects.create(
            ebook=ebook,
            order=1,
            title="Lesson",
            start_page=1,
            is_verified=True,
        )
        return ebook

    @override_settings(EBOOK_SYSTEM_ENABLED=False, EBOOK_WEB_READER_ENABLED=True, EBOOK_MOBILE_READER_ENABLED=True)
    def test_global_disabled_overrides_per_book_flags(self):
        ebook = self.create_ebook()

        self.assertFalse(is_web_reader_available(ebook, self.staff))
        self.assertFalse(is_mobile_reader_available(ebook, self.staff))

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=False)
    def test_per_book_web_disable_blocks_web_reader(self):
        ebook = self.create_ebook(new_ebook_reader_web_enabled=False)

        response = self.client.get(reverse("ebook_reader:web_reader", args=[ebook.id]))

        self.assertEqual(response.status_code, 404)

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_MOBILE_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=False)
    def test_per_book_mobile_disable_hides_api(self):
        ebook = self.create_ebook(new_ebook_reader_mobile_enabled=False)

        response = self.client.get(reverse("ebook_v1_detail", args=[ebook.id]))

        self.assertEqual(response.status_code, 404)

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_MOBILE_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=True)
    def test_staff_only_mode_blocks_anonymous_mobile_api(self):
        ebook = self.create_ebook()

        response = self.client.get(reverse("ebook_v1_detail", args=[ebook.id]))

        self.assertEqual(response.status_code, 404)

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_PROCESSING_ENABLED=False)
    def test_processing_disabled_skips_background_task(self):
        ebook = self.create_ebook()

        result = inspect_ebook_document.apply(args=[ebook.id]).get()

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "processing_disabled")

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=False)
    def test_non_ready_ebook_never_uses_new_reader(self):
        ebook = self.create_ebook(status=EbookDocument.Status.REVIEW_REQUIRED)

        response = self.client.get(reverse("ebook_reader:web_reader", args=[ebook.id]))

        self.assertEqual(response.status_code, 404)

    @override_settings(EBOOK_SYSTEM_ENABLED=False, EBOOK_WEB_READER_ENABLED=True, EBOOK_PROCESSING_ENABLED=True)
    def test_system_check_warns_for_overridden_flags(self):
        messages = ebook_reader_production_checks(None)

        self.assertTrue(
            any(isinstance(message, Warning) and message.id == "ebook_reader.W001" for message in messages)
        )

    @override_settings(EBOOK_MAX_PDF_PAGES=0)
    def test_system_check_errors_for_invalid_pdf_limit(self):
        messages = ebook_reader_production_checks(None)

        self.assertTrue(
            any(isinstance(message, Error) and message.id == "ebook_reader.E003" for message in messages)
        )

    @override_settings(EBOOK_SYSTEM_ENABLED=False, EBOOK_WEB_READER_ENABLED=True)
    def test_old_reader_fallback_url_still_works_when_new_system_disabled(self):
        ebook = self.create_ebook()
        chapter = Chapter.objects.create(book=ebook.book, title="Legacy", order=1)
        page = BookPage.objects.create(chapter=chapter, page_number=1, content="Old reader")

        response = self.client.get(reverse("web_reader_page", args=[page.id]))

        self.assertEqual(response.status_code, 200)
