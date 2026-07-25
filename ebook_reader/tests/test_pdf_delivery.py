import tempfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from ebook_reader.models import EbookDocument, EbookLesson
from library.models import Book, Category


PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
)


class EbookPdfDeliveryTests(TestCase):
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
        self.staff = get_user_model().objects.create_superuser(
            username="staff",
            email="staff@example.com",
            password="pass",
        )

    def create_ebook(
        self,
        *,
        status=EbookDocument.Status.READY,
        published=True,
        with_pdf=True,
        pdf_bytes=PDF_BYTES,
        title="Stream Book",
    ):
        book = Book.objects.create(
            title=title,
            slug=f"{title.lower().replace(' ', '-')}-{Book.objects.count()}",
            category=self.category,
            is_published=published,
        )
        if with_pdf:
            book.pdf_file.save("stream-book.pdf", ContentFile(pdf_bytes), save=True)
        ebook = EbookDocument.objects.create(
            book=book,
            status=status,
            new_ebook_reader_enabled=True,
            new_ebook_reader_mobile_enabled=True,
            new_ebook_reader_web_enabled=True,
            total_pdf_pages=10,
            page_mapping_status=EbookDocument.PageMappingStatus.ACCEPTED,
        )
        EbookLesson.objects.create(
            ebook=ebook,
            order=1,
            title="First Lesson",
            start_page=1,
            is_verified=True,
        )
        return ebook

    def read_streaming_body(self, response):
        if getattr(response, "streaming", False):
            return b"".join(response.streaming_content)
        return response.content

    def test_authorised_ready_ebook_streams_pdf(self):
        ebook = self.create_ebook()

        response = self.client.get(reverse("ebook_v1_pdf_access", args=[ebook.id]))
        body = self.read_streaming_body(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertEqual(int(response["Content-Length"]), len(PDF_BYTES))
        self.assertEqual(body, PDF_BYTES)

    def test_unauthorised_unpublished_ebook_is_not_accessible(self):
        ebook = self.create_ebook(published=False)

        response = self.client.get(reverse("ebook_v1_pdf_access", args=[ebook.id]))

        self.assertEqual(response.status_code, 404)

    def test_staff_can_access_unpublished_ebook(self):
        ebook = self.create_ebook(published=False)
        self.client.force_authenticate(self.staff)

        response = self.client.get(reverse("ebook_v1_pdf_access", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.read_streaming_body(response)

    def test_non_ready_ebook_is_hidden(self):
        ebook = self.create_ebook(status=EbookDocument.Status.REVIEW_REQUIRED)

        response = self.client.get(reverse("ebook_v1_pdf_access", args=[ebook.id]))

        self.assertEqual(response.status_code, 404)

    def test_missing_pdf_returns_not_found(self):
        ebook = self.create_ebook(with_pdf=False)

        response = self.client.get(reverse("ebook_v1_pdf_access", args=[ebook.id]))

        self.assertEqual(response.status_code, 404)

    def test_corrupt_pdf_is_rejected_without_path_leakage(self):
        ebook = self.create_ebook(pdf_bytes=b"not a pdf")

        response = self.client.get(reverse("ebook_v1_pdf_access", args=[ebook.id]))

        self.assertEqual(response.status_code, 422)
        self.assertNotIn(str(self.temp_media.name), self.read_streaming_body(response).decode())

    def test_first_byte_range(self):
        ebook = self.create_ebook()

        response = self.client.get(
            reverse("ebook_v1_pdf_access", args=[ebook.id]),
            HTTP_RANGE="bytes=0-3",
        )

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], f"bytes 0-3/{len(PDF_BYTES)}")
        self.assertEqual(response["Content-Length"], "4")
        self.assertEqual(self.read_streaming_body(response), b"%PDF")

    def test_middle_byte_range(self):
        ebook = self.create_ebook()

        response = self.client.get(
            reverse("ebook_v1_pdf_access", args=[ebook.id]),
            HTTP_RANGE="bytes=5-8",
        )

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], f"bytes 5-8/{len(PDF_BYTES)}")
        self.assertEqual(self.read_streaming_body(response), PDF_BYTES[5:9])

    def test_suffix_byte_range(self):
        ebook = self.create_ebook()

        response = self.client.get(
            reverse("ebook_v1_pdf_access", args=[ebook.id]),
            HTTP_RANGE="bytes=-5",
        )

        self.assertEqual(response.status_code, 206)
        self.assertEqual(self.read_streaming_body(response), PDF_BYTES[-5:])

    def test_invalid_range_returns_416(self):
        ebook = self.create_ebook()

        response = self.client.get(
            reverse("ebook_v1_pdf_access", args=[ebook.id]),
            HTTP_RANGE=f"bytes={len(PDF_BYTES) + 10}-{len(PDF_BYTES) + 20}",
        )

        self.assertEqual(response.status_code, 416)
        self.assertEqual(response["Content-Range"], f"bytes */{len(PDF_BYTES)}")

    def test_head_request_returns_headers_without_body(self):
        ebook = self.create_ebook()

        response = self.client.head(reverse("ebook_v1_pdf_access", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Content-Length"], str(len(PDF_BYTES)))
        self.assertEqual(response.content, b"")

    def test_reader_config_documents_local_streaming_mode(self):
        ebook = self.create_ebook()

        response = self.client.get(reverse("ebook_v1_reader_config", args=[ebook.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["pdf_access_method"], "authenticated_stream")
        self.assertIn("/api/v1/ebooks/", response.data["reader_url"])
        self.assertIn("/pdf-access/", response.data["reader_url"])
        self.assertIsNone(response.data["expires_at"])

    def test_cross_book_access_cannot_bypass_publication_rules(self):
        self.create_ebook(title="Allowed Book")
        hidden = self.create_ebook(title="Hidden Book", published=False)

        response = self.client.get(reverse("ebook_v1_pdf_access", args=[hidden.id]))

        self.assertEqual(response.status_code, 404)

    def test_pdf_response_does_not_leak_filesystem_path(self):
        ebook = self.create_ebook()

        response = self.client.get(reverse("ebook_v1_pdf_access", args=[ebook.id]))
        headers = " ".join(str(value) for value in response.headers.values())

        self.assertNotIn(str(self.temp_media.name), headers)
        self.assertNotIn("C:\\", headers)
        self.read_streaming_body(response)

    def test_existing_book_api_remains_unchanged(self):
        self.create_ebook()

        response = self.client.get("/api/books/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.data)
