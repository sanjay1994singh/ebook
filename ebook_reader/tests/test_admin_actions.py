from django.test import TestCase

from ebook_reader.models import EbookDocument, EbookLesson
from ebook_reader.services.admin_actions import (
    mark_ready_when_verified,
    reset_to_pending,
)
from library.models import Book, Category


class EbookAdminActionTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Vani")

    def create_document(self, title, status=EbookDocument.Status.PENDING):
        book = Book.objects.create(
            title=title,
            slug=title.lower().replace(" ", "-"),
            category=self.category,
        )
        return EbookDocument.objects.create(book=book, status=status)

    def test_mark_ready_updates_only_documents_with_verified_lessons(self):
        ready_document = self.create_document("Ready Book")
        EbookLesson.objects.create(
            ebook=ready_document,
            order=1,
            title="Verified lesson",
            start_page=1,
            is_verified=True,
        )
        unverified_document = self.create_document("Unverified Book")
        EbookLesson.objects.create(
            ebook=unverified_document,
            order=1,
            title="Unverified lesson",
            start_page=1,
            is_verified=False,
        )

        result = mark_ready_when_verified(EbookDocument.objects.all())

        ready_document.refresh_from_db()
        unverified_document.refresh_from_db()
        self.assertEqual(result.updated, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(ready_document.status, EbookDocument.Status.READY)
        self.assertEqual(unverified_document.status, EbookDocument.Status.PENDING)

    def test_mark_ready_skips_documents_without_lessons(self):
        document = self.create_document("Empty Book")

        result = mark_ready_when_verified(EbookDocument.objects.all())

        document.refresh_from_db()
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(document.status, EbookDocument.Status.PENDING)

    def test_reset_to_pending_updates_selected_documents(self):
        document = self.create_document("Ready Book", EbookDocument.Status.READY)

        updated = reset_to_pending(EbookDocument.objects.filter(id=document.id))

        document.refresh_from_db()
        self.assertEqual(updated, 1)
        self.assertEqual(document.status, EbookDocument.Status.PENDING)
