from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ebook_reader.models import EbookDocument, EbookLesson
from library.models import Book, Category


class AdminTocReviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
        )
        self.category = Category.objects.create(name="Vani")
        self.book = Book.objects.create(
            title="Review Book",
            slug="review-book",
            category=self.category,
        )
        self.document = EbookDocument.objects.create(
            book=self.book,
            toc_mode=EbookDocument.TocMode.MANUAL,
            toc_start_page=2,
            toc_end_page=3,
            detected_toc_start_page=4,
            detected_toc_end_page=5,
            toc_detection_confidence=0.8,
            total_pdf_pages=100,
            page_mapping_mode=EbookDocument.PageMappingMode.MANUAL_OFFSET,
            page_number_offset=0,
        )
        self.lesson = EbookLesson.objects.create(
            ebook=self.document,
            order=1,
            title="First lesson",
            printed_page_number=10,
            start_page=10,
            source_toc_page=2,
            confidence=0.9,
        )
        self.url = reverse(
            "admin:ebook_reader_ebookdocument_review_toc",
            args=[self.document.id],
        )

    def login(self):
        self.client.force_login(self.user)

    def test_permission_required(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)

    def test_review_page_loads_for_admin(self):
        self.login()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Review TOC")
        self.assertContains(response, "Review Book")

    def test_valid_edit_marks_row_manual(self):
        self.login()
        data = self.form_data(
            {
                "lessons-0-title": "Updated lesson",
                "lessons-0-start_page": "12",
            }
        )

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 302)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.title, "Updated lesson")
        self.assertEqual(self.lesson.start_page, 12)
        self.assertTrue(self.lesson.is_manually_edited)

    def test_invalid_page_rejected(self):
        self.login()
        data = self.form_data({"lessons-0-start_page": "101"})

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Start page cannot exceed total PDF pages")
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.start_page, 10)

    def test_duplicate_order_rejected(self):
        second = EbookLesson.objects.create(
            ebook=self.document,
            order=2,
            title="Second",
            start_page=20,
        )
        self.login()
        data = self.form_data(
            {
                "lessons-TOTAL_FORMS": "2",
                "lessons-1-id": str(second.id),
                "lessons-1-order": "1",
                "lessons-1-title": "Second",
                "lessons-1-printed_page_number": "",
                "lessons-1-start_page": "20",
                "lessons-1-end_page": "",
                "lessons-1-source_toc_page": "",
                "lessons-1-confidence": "",
                "lessons-1-parser_strategy": "",
                "lessons-1-warnings": "[]",
            }
        )

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Duplicate lesson order")

    def test_invalid_row_cannot_be_verified(self):
        self.login()
        data = self.form_data(
            {
                "lessons-0-title": "",
                "lessons-0-is_verified": "on",
            }
        )

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Verified lessons must have a title")

    def test_bulk_verification_records_user_and_time(self):
        self.login()
        data = self.form_data(
            {
                "action": "mark_selected_verified",
                "lessons-0-selected": "on",
            }
        )

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 302)
        self.lesson.refresh_from_db()
        self.assertTrue(self.lesson.is_verified)
        self.assertEqual(self.lesson.verified_by, self.user)
        self.assertIsNotNone(self.lesson.verified_at)

    def test_mark_all_valid_rows_verified(self):
        self.login()

        response = self.client.post(self.url, {"action": "mark_all_valid_verified"})

        self.assertEqual(response.status_code, 302)
        self.lesson.refresh_from_db()
        self.assertTrue(self.lesson.is_verified)

    def test_toc_range_edit(self):
        self.login()
        data = self.form_data(
            {
                "settings-toc_start_page": "6",
                "settings-toc_end_page": "8",
            }
        )

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 302)
        self.document.refresh_from_db()
        self.assertEqual((self.document.toc_start_page, self.document.toc_end_page), (6, 8))

    def test_accepting_detected_range(self):
        self.login()

        response = self.client.post(self.url, {"action": "accept_detected_range"})

        self.assertEqual(response.status_code, 302)
        self.document.refresh_from_db()
        self.assertEqual((self.document.toc_start_page, self.document.toc_end_page), (4, 5))

    def test_rerun_protects_verified_rows(self):
        self.lesson.is_verified = True
        self.lesson.save()
        self.login()
        with patch("ebook_reader.admin.rerun_processing") as mocked_rerun:
            mocked_rerun.return_value.status = "review_required"

            response = self.client.post(self.url, {"action": "rerun_processing"})

        self.assertEqual(response.status_code, 302)
        mocked_rerun.assert_called_once()
        self.assertFalse(mocked_rerun.call_args.kwargs["force"])

    def test_force_rerun_requires_confirmation(self):
        self.login()
        with patch("ebook_reader.admin.rerun_processing") as mocked_rerun:
            response = self.client.post(self.url, {"action": "force_rerun_processing"})

        self.assertEqual(response.status_code, 302)
        mocked_rerun.assert_not_called()

    def test_pagination_supports_more_than_100_rows(self):
        for index in range(2, 122):
            EbookLesson.objects.create(
                ebook=self.document,
                order=index,
                title=f"Lesson {index}",
                start_page=index,
            )
        self.login()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Page 1 of 3")

    def test_old_book_admin_still_loads(self):
        self.login()
        url = reverse("admin:library_book_change", args=[self.book.id])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

    def form_data(self, overrides=None):
        data = {
            "action": "save",
            "settings-toc_mode": self.document.toc_mode,
            "settings-toc_start_page": str(self.document.toc_start_page),
            "settings-toc_end_page": str(self.document.toc_end_page),
            "settings-page_mapping_mode": self.document.page_mapping_mode,
            "settings-page_number_offset": str(self.document.page_number_offset),
            "anchors-TOTAL_FORMS": "2",
            "anchors-INITIAL_FORMS": "0",
            "anchors-MIN_NUM_FORMS": "0",
            "anchors-MAX_NUM_FORMS": "1000",
            "anchors-0-printed_page_number": "",
            "anchors-0-physical_pdf_page": "",
            "anchors-0-note": "",
            "anchors-1-printed_page_number": "",
            "anchors-1-physical_pdf_page": "",
            "anchors-1-note": "",
            "lessons-TOTAL_FORMS": "1",
            "lessons-INITIAL_FORMS": "1",
            "lessons-MIN_NUM_FORMS": "0",
            "lessons-MAX_NUM_FORMS": "1000",
            "lessons-0-id": str(self.lesson.id),
            "lessons-0-order": str(self.lesson.order),
            "lessons-0-title": self.lesson.title,
            "lessons-0-printed_page_number": str(self.lesson.printed_page_number),
            "lessons-0-start_page": str(self.lesson.start_page),
            "lessons-0-end_page": "",
            "lessons-0-source_toc_page": str(self.lesson.source_toc_page),
            "lessons-0-confidence": str(self.lesson.confidence),
            "lessons-0-parser_strategy": self.lesson.parser_strategy,
            "lessons-0-warnings": "[]",
        }
        if overrides:
            data.update(overrides)
        return data
