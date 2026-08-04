import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from ebook_reader.models import EbookDocument, EbookLesson, EbookReadingProgress
from library.models import Book, BookPage, Category, Chapter


class EbookApiV1Tests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_media = tempfile.TemporaryDirectory()
        cls.override_settings = override_settings(
            MEDIA_ROOT=cls.temp_media.name,
            EBOOK_SYSTEM_ENABLED=True,
            EBOOK_MOBILE_READER_ENABLED=True,
            EBOOK_READER_STAFF_ONLY=False,
        )
        cls.override_settings.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.override_settings.disable()
        cls.temp_media.cleanup()

    def setUp(self):
        self.client = APIClient()
        self.category = Category.objects.create(name="Vani", slug="vani")
        self.user = get_user_model().objects.create_user(
            username="user",
            password="pass",
        )
        self.staff = get_user_model().objects.create_superuser(
            username="staff",
            email="staff@example.com",
            password="pass",
        )

    def create_ebook(self, *, status=EbookDocument.Status.READY, published=True, title="Ready Book", lessons=2):
        book = Book.objects.create(
            title=title,
            slug=f"{title.lower().replace(' ', '-')}-{Book.objects.count()}",
            category=self.category,
            author="Author",
            description="Short description",
            is_published=published,
        )
        book.cover_image.save("cover.jpg", ContentFile(b"cover"), save=True)
        book.pdf_file.save("book.pdf", ContentFile(b"%PDF-1.4\n%%EOF"), save=True)
        ebook = EbookDocument.objects.create(
            book=book,
            status=status,
            new_ebook_reader_enabled=True,
            new_ebook_reader_mobile_enabled=True,
            new_ebook_reader_web_enabled=True,
            total_pdf_pages=120,
            page_mapping_status=EbookDocument.PageMappingStatus.ACCEPTED,
            page_mapping_mode=EbookDocument.PageMappingMode.MANUAL_OFFSET,
            page_number_offset=0,
        )
        for index in range(1, lessons + 1):
            EbookLesson.objects.create(
                ebook=ebook,
                order=index,
                title=f"Lesson {index}",
                printed_page_number=index,
                start_page=index + 5,
                end_page=index + 6,
                is_verified=True,
            )
        return ebook

    def test_ready_accessible_ebook_listed(self):
        ebook = self.create_ebook()

        response = self.client.get(reverse("ebook_v1_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], ebook.id)
        self.assertTrue(response.data["results"][0]["reader_available"])

    def test_ready_inaccessible_unpublished_book_hidden(self):
        self.create_ebook(published=False)

        response = self.client.get(reverse("ebook_v1_list"))

        self.assertEqual(response.data["count"], 0)

    def test_review_required_ebook_hidden(self):
        self.create_ebook(status=EbookDocument.Status.REVIEW_REQUIRED)

        response = self.client.get(reverse("ebook_v1_list"))

        self.assertEqual(response.data["count"], 0)

    def test_failed_ebook_hidden(self):
        self.create_ebook(status=EbookDocument.Status.FAILED)

        response = self.client.get(reverse("ebook_v1_list"))

        self.assertEqual(response.data["count"], 0)

    def test_lessons_contain_verified_rows_only_and_ordered(self):
        ebook = self.create_ebook(lessons=1)
        EbookLesson.objects.create(
            ebook=ebook,
            order=2,
            title="Hidden draft",
            start_page=20,
            is_verified=False,
            raw_ocr_text="secret",
            parser_strategy="internal",
        )

        response = self.client.get(reverse("ebook_v1_lessons", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["title"], "Lesson 1")
        self.assertNotIn("raw_ocr_text", response.data[0])
        self.assertNotIn("parser_strategy", response.data[0])

    def test_anonymous_access_allowed_by_current_policy(self):
        ebook = self.create_ebook()

        response = self.client.get(reverse("ebook_v1_detail", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["access_restrictions"]["requires_authentication"])

    def test_authenticated_progress_summary(self):
        ebook = self.create_ebook()
        chapter = Chapter.objects.create(book=ebook.book, title="Chapter", order=1)
        page = BookPage.objects.create(chapter=chapter, title="Page", page_number=1, content="x")
        EbookReadingProgress.objects.create(
            user=self.user,
            ebook_document=ebook,
            current_page=25,
            current_lesson=ebook.lessons.order_by("order").first(),
            percentage=25,
            last_read_at=page.chapter.book.updated_at,
        )
        self.client.force_authenticate(self.user)

        response = self.client.get(reverse("ebook_v1_detail", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.data["progress_summary"]["percentage"]), "25.00")
        self.assertEqual(response.data["continue_reading_page"]["pdf_page"], 25)

    def test_absolute_cover_urls_and_no_filesystem_paths(self):
        ebook = self.create_ebook()

        response = self.client.get(reverse("ebook_v1_detail", args=[ebook.id]), HTTP_HOST="testserver")
        payload = str(response.data)

        self.assertTrue(response.data["cover_image_url"].startswith("http://testserver/"))
        self.assertNotIn("C:\\", payload)
        self.assertNotIn(str(self.temp_media.name), payload)

    def test_query_count_for_list_and_detail(self):
        for index in range(5):
            self.create_ebook(title=f"Ready Book {index}")

        with CaptureQueriesContext(connection) as list_context:
            self.client.get(reverse("ebook_v1_list"))
        with CaptureQueriesContext(connection) as detail_context:
            first = EbookDocument.objects.filter(status=EbookDocument.Status.READY).first()
            self.client.get(reverse("ebook_v1_detail", args=[first.id]))

        self.assertLessEqual(len(list_context), 8)
        self.assertLessEqual(len(detail_context), 8)

    def test_ebook_with_more_than_100_lessons(self):
        ebook = self.create_ebook(lessons=0)
        for index in range(1, 121):
            EbookLesson.objects.create(
                ebook=ebook,
                order=index,
                title=f"Lesson {index}",
                start_page=index,
                is_verified=True,
            )

        response = self.client.get(reverse("ebook_v1_reader_config", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["lessons"]), 120)

    def test_reader_config_returns_safe_endpoint_url(self):
        ebook = self.create_ebook()

        response = self.client.get(reverse("ebook_v1_reader_config", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["pdf_access_method"], "authenticated_stream")
        self.assertIn("/api/v1/ebooks/", response.data["reader_url"])
        self.assertIn("/pdf-access/", response.data["reader_url"])
        self.assertNotIn("book_pdfs", response.data["reader_url"])

    def test_staff_only_diagnostics(self):
        ebook = self.create_ebook()

        anonymous = self.client.get(reverse("ebook_v1_diagnostics", args=[ebook.id]))
        self.client.force_authenticate(self.staff)
        staff_response = self.client.get(reverse("ebook_v1_diagnostics", args=[ebook.id]))

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(staff_response.status_code, 200)
        self.assertIn("processing_metadata", staff_response.data)

    def test_existing_book_api_remains_unchanged(self):
        self.create_ebook()

        response = self.client.get("/api/books/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.data)
