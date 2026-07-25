import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from ebook_reader.models import EbookDocument, EbookLesson, EbookReadingProgress
from library.models import Book, Category


class EbookProgressApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_media = tempfile.TemporaryDirectory()
        cls.override_media = override_settings(
            MEDIA_ROOT=cls.temp_media.name,
            EBOOK_SYSTEM_ENABLED=True,
            EBOOK_MOBILE_READER_ENABLED=True,
            EBOOK_READER_STAFF_ONLY=False,
        )
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
        self.user = get_user_model().objects.create_user(username="user", password="pass")
        self.other_user = get_user_model().objects.create_user(username="other", password="pass")

    def create_ebook(self, *, published=True, status=EbookDocument.Status.READY, lessons=True):
        book = Book.objects.create(
            title=f"Progress Book {Book.objects.count()}",
            slug=f"progress-book-{Book.objects.count()}",
            category=self.category,
            is_published=published,
        )
        book.pdf_file.save("progress.pdf", ContentFile(b"%PDF-1.4\n%%EOF"), save=True)
        ebook = EbookDocument.objects.create(
            book=book,
            status=status,
            new_ebook_reader_enabled=True,
            new_ebook_reader_mobile_enabled=True,
            new_ebook_reader_web_enabled=True,
            total_pdf_pages=100,
            page_mapping_status=EbookDocument.PageMappingStatus.ACCEPTED,
        )
        if lessons:
            EbookLesson.objects.create(
                ebook=ebook,
                order=1,
                title="First",
                start_page=1,
                end_page=20,
                is_verified=True,
            )
            EbookLesson.objects.create(
                ebook=ebook,
                order=2,
                title="Second",
                start_page=21,
                is_verified=True,
            )
        return ebook

    def test_create_progress(self):
        ebook = self.create_ebook()
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            reverse("ebook_v1_progress", args=[ebook.id]),
            {"current_page": 10},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["current_page"], 10)
        self.assertEqual(str(response.data["percentage"]), "10.00")
        self.assertEqual(response.data["current_lesson"]["title"], "First")
        self.assertFalse(response.data["completed"])
        self.assertEqual(EbookReadingProgress.objects.count(), 1)

    def test_update_progress_reuses_same_row(self):
        ebook = self.create_ebook()
        self.client.force_authenticate(self.user)

        self.client.patch(reverse("ebook_v1_progress", args=[ebook.id]), {"current_page": 10}, format="json")
        response = self.client.patch(
            reverse("ebook_v1_progress", args=[ebook.id]),
            {"current_page": 25},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(EbookReadingProgress.objects.count(), 1)
        self.assertEqual(response.data["current_lesson"]["title"], "Second")

    def test_get_progress_returns_existing_row(self):
        ebook = self.create_ebook()
        progress = EbookReadingProgress.objects.create(
            user=self.user,
            ebook_document=ebook,
            current_page=40,
            percentage="40.00",
            last_read_at=timezone.now(),
        )
        self.client.force_authenticate(self.user)

        response = self.client.get(reverse("ebook_v1_progress", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["current_page"], progress.current_page)
        self.assertEqual(str(response.data["percentage"]), "40.00")

    def test_invalid_page_below_one(self):
        ebook = self.create_ebook()
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            reverse("ebook_v1_progress", args=[ebook.id]),
            {"current_page": 0},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_page_above_total(self):
        ebook = self.create_ebook()
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            reverse("ebook_v1_progress", args=[ebook.id]),
            {"current_page": 101},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_percentage_calculation_near_final_page(self):
        ebook = self.create_ebook()
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            reverse("ebook_v1_progress", args=[ebook.id]),
            {"current_page": 100},
            format="json",
        )

        self.assertEqual(str(response.data["percentage"]), "100.00")
        self.assertTrue(response.data["completed"])

    def test_user_isolation(self):
        ebook = self.create_ebook()
        EbookReadingProgress.objects.create(
            user=self.other_user,
            ebook_document=ebook,
            current_page=70,
            percentage="70.00",
            last_read_at=timezone.now(),
        )
        self.client.force_authenticate(self.user)

        response = self.client.get(reverse("ebook_v1_progress", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["current_page"])

    def test_unauthenticated_progress_requires_login(self):
        ebook = self.create_ebook()

        response = self.client.get(reverse("ebook_v1_progress", args=[ebook.id]))

        self.assertEqual(response.status_code, 401)

    def test_unauthorised_unpublished_ebook_hidden(self):
        ebook = self.create_ebook(published=False)
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            reverse("ebook_v1_progress", args=[ebook.id]),
            {"current_page": 10},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_ebook_without_lessons_still_saves_page(self):
        ebook = self.create_ebook(lessons=False)
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            reverse("ebook_v1_progress", args=[ebook.id]),
            {"current_page": 5},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["current_page"], 5)
        self.assertIsNone(response.data["current_lesson"])

    def test_client_percentage_and_lesson_are_ignored(self):
        ebook = self.create_ebook()
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            reverse("ebook_v1_progress", args=[ebook.id]),
            {"current_page": 10, "percentage": "99.99", "current_lesson": 999},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.data["percentage"]), "10.00")
        self.assertEqual(response.data["current_lesson"]["title"], "First")
