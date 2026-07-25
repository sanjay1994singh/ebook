from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from ebook_reader.models import EbookDocument, EbookLesson
from library.models import Book, Category


class EbookReaderModelTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Vani")
        self.book = Book.objects.create(
            title="Anmol Vachan",
            slug="anmol-vachan",
            category=self.category,
        )

    def test_ebook_document_reuses_existing_book_record(self):
        document = EbookDocument.objects.create(
            book=self.book,
            status=EbookDocument.Status.PENDING,
            total_pdf_pages=50,
        )

        self.assertEqual(document.book, self.book)
        self.assertEqual(self.book.ebook_document, document)
        self.assertEqual(document.status, EbookDocument.Status.PENDING)

    def test_lessons_belong_to_document_and_order_by_order_field(self):
        document = EbookDocument.objects.create(book=self.book)
        second = EbookLesson.objects.create(
            ebook=document,
            order=2,
            title="Second lesson",
            start_page=10,
        )
        first = EbookLesson.objects.create(
            ebook=document,
            order=1,
            title="First lesson",
            start_page=1,
        )

        self.assertEqual(second.ebook, document)
        self.assertEqual(document.lessons.count(), 2)
        self.assertEqual(list(document.lessons.all()), [first, second])

    def test_lesson_order_is_unique_per_document(self):
        document = EbookDocument.objects.create(book=self.book)
        EbookLesson.objects.create(
            ebook=document,
            order=1,
            title="First lesson",
            start_page=1,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EbookLesson.objects.create(
                    ebook=document,
                    order=1,
                    title="Duplicate order",
                    start_page=2,
                )

    def test_lesson_start_page_must_be_at_least_one(self):
        document = EbookDocument.objects.create(book=self.book)
        lesson = EbookLesson(
            ebook=document,
            order=1,
            title="Invalid start",
            start_page=0,
        )

        with self.assertRaises(ValidationError):
            lesson.full_clean()

    def test_lesson_end_page_must_not_be_before_start_page(self):
        document = EbookDocument.objects.create(book=self.book)
        lesson = EbookLesson(
            ebook=document,
            order=1,
            title="Invalid end",
            start_page=5,
            end_page=4,
        )

        with self.assertRaises(ValidationError):
            lesson.full_clean()

    def test_lesson_without_end_page_is_valid(self):
        document = EbookDocument.objects.create(book=self.book)
        lesson = EbookLesson(
            ebook=document,
            order=1,
            title="Open ended lesson",
            start_page=5,
        )

        lesson.full_clean()

    def test_toc_end_page_requires_valid_start_page(self):
        document = EbookDocument(book=self.book, toc_end_page=4)

        with self.assertRaises(ValidationError):
            document.full_clean()
