import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from ebook_reader.models import EbookDocument, EbookLesson, EbookReadingProgress
from library.models import Book, BookPage, Category, Chapter


PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


class EbookWebReaderTests(TestCase):
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
        self.category = Category.objects.create(name="Vani", slug="vani")
        self.staff = get_user_model().objects.create_superuser(
            username="staff",
            email="staff@example.com",
            password="pass",
        )
        self.user = get_user_model().objects.create_user(
            username="reader",
            password="pass",
        )

    def create_ebook(
        self,
        *,
        status=EbookDocument.Status.READY,
        published=True,
        lessons=True,
        total_pdf_pages=60,
    ):
        book = Book.objects.create(
            title="Beta Book",
            slug=f"beta-book-{Book.objects.count()}",
            category=self.category,
            is_published=published,
        )
        book.pdf_file.save("beta-book.pdf", ContentFile(PDF_BYTES), save=True)
        chapter = Chapter.objects.create(book=book, title="Legacy Chapter", order=1)
        page = BookPage.objects.create(
            chapter=chapter,
            title="Legacy Page",
            page_number=1,
            content="Legacy content",
        )
        ebook = EbookDocument.objects.create(
            book=book,
            status=status,
            new_ebook_reader_enabled=True,
            new_ebook_reader_web_enabled=True,
            new_ebook_reader_mobile_enabled=True,
            total_pdf_pages=total_pdf_pages,
            page_mapping_status=EbookDocument.PageMappingStatus.ACCEPTED,
        )
        if lessons:
            EbookLesson.objects.create(
                ebook=ebook,
                order=1,
                title="Lesson One",
                start_page=5,
                end_page=10,
                is_verified=True,
            )
            EbookLesson.objects.create(
                ebook=ebook,
                order=2,
                title="Lesson Two",
                start_page=20,
                is_verified=True,
            )
            EbookLesson.objects.create(
                ebook=ebook,
                order=3,
                title="Draft Lesson",
                start_page=30,
                is_verified=False,
            )
        return ebook, page

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=True)
    def test_ready_ebook_opens_for_staff(self):
        ebook, _page = self.create_ebook()
        self.client.force_login(self.staff)

        response = self.client.get(reverse("ebook_reader:web_reader", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Beta ebook reader")
        self.assertContains(response, "Lesson One")
        self.assertContains(response, "/api/v1/ebooks/")
        self.assertContains(response, "/pdf-access/")

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=True)
    def test_review_required_ebook_denied(self):
        ebook, _page = self.create_ebook(status=EbookDocument.Status.REVIEW_REQUIRED)
        self.client.force_login(self.staff)

        response = self.client.get(reverse("ebook_reader:web_reader", args=[ebook.id]))

        self.assertEqual(response.status_code, 404)

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=False)
    def test_unpublished_book_denied_for_normal_user(self):
        ebook, _page = self.create_ebook(published=False)
        self.client.force_login(self.user)

        response = self.client.get(reverse("ebook_reader:web_reader", args=[ebook.id]))

        self.assertEqual(response.status_code, 403)

    @override_settings(EBOOK_SYSTEM_ENABLED=False, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=True)
    def test_feature_flag_disabled(self):
        ebook, _page = self.create_ebook()
        self.client.force_login(self.staff)

        response = self.client.get(reverse("ebook_reader:web_reader", args=[ebook.id]))

        self.assertEqual(response.status_code, 404)

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=True)
    def test_staff_only_mode_denies_normal_user(self):
        ebook, _page = self.create_ebook()
        self.client.force_login(self.user)

        response = self.client.get(reverse("ebook_reader:web_reader", args=[ebook.id]))

        self.assertEqual(response.status_code, 403)

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=True)
    def test_page_query_uses_physical_pdf_page(self):
        ebook, _page = self.create_ebook()
        EbookReadingProgress.objects.create(
            user=self.staff,
            ebook_document=ebook,
            current_page=30,
            percentage="50.00",
            last_read_at=ebook.updated_at,
        )
        self.client.force_login(self.staff)

        response = self.client.get(
            reverse("ebook_reader:web_reader", args=[ebook.id]),
            {"page": 20},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"initialPage": 20')
        self.assertContains(response, "Lesson Two")

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=True)
    def test_saved_progress_used_when_no_explicit_page(self):
        ebook, _page = self.create_ebook()
        EbookReadingProgress.objects.create(
            user=self.staff,
            ebook_document=ebook,
            current_page=20,
            percentage="33.33",
            last_read_at=ebook.updated_at,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("ebook_reader:web_reader", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"initialPage": 20')

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=True)
    def test_invalid_page_falls_back_safely(self):
        ebook, _page = self.create_ebook(total_pdf_pages=40)
        self.client.force_login(self.staff)

        invalid = self.client.get(
            reverse("ebook_reader:web_reader", args=[ebook.id]),
            {"page": "bad"},
        )
        too_high = self.client.get(
            reverse("ebook_reader:web_reader", args=[ebook.id]),
            {"page": 999},
        )

        self.assertContains(invalid, '"initialPage": 1')
        self.assertContains(too_high, '"initialPage": 40')

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=True)
    def test_unverified_lessons_are_not_in_reader_payload(self):
        ebook, _page = self.create_ebook()
        self.client.force_login(self.staff)

        response = self.client.get(reverse("ebook_reader:web_reader", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lesson One")
        self.assertNotContains(response, "Draft Lesson")

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=True)
    def test_old_reader_url_remains_unchanged(self):
        _ebook, page = self.create_ebook()

        self.assertEqual(reverse("web_reader_page", args=[page.id]), f"/web/reader/{page.id}/")

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=True)
    def test_book_detail_shows_preview_link_for_staff_only(self):
        ebook, _page = self.create_ebook()
        url = reverse("web_book_detail", args=[ebook.book.slug])

        public_response = self.client.get(url)
        self.client.force_login(self.staff)
        staff_response = self.client.get(url)

        self.assertNotContains(public_response, "New reader preview")
        self.assertContains(staff_response, "New reader preview")
        self.assertContains(
            staff_response,
            reverse("ebook_reader:web_reader", args=[ebook.id]),
        )

    @override_settings(EBOOK_SYSTEM_ENABLED=True, EBOOK_WEB_READER_ENABLED=True, EBOOK_READER_STAFF_ONLY=False)
    def test_public_mode_allows_ready_published_ebook(self):
        ebook, _page = self.create_ebook()

        response = self.client.get(reverse("ebook_reader:web_reader", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)

