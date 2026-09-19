import tempfile

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from pypdf import PdfWriter

from ebook_reader.models import EbookDocument, EbookLesson
from ebook_reader.services.index_preparation import prepare_book_index
from ebook_reader.services.index_sync import sync_lessons_to_book_chapters
from library.models import Book, Category, Chapter


def blank_pdf_bytes(page_count=8):
    writer = PdfWriter()
    for _index in range(page_count):
        writer.add_blank_page(width=300, height=300)
    from io import BytesIO

    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class IndexSyncTests(TestCase):
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
        category = Category.objects.create(name="Vani")
        self.book = Book.objects.create(title="Index Book", slug="index-book", category=category)
        self.book.pdf_file.save("index.pdf", ContentFile(blank_pdf_bytes()), save=True)
        self.document = EbookDocument.objects.create(
            book=self.book,
            total_pdf_pages=8,
            page_mapping_mode=EbookDocument.PageMappingMode.MANUAL_OFFSET,
            page_number_offset=1,
        )

    def test_lessons_sync_to_public_chapters_with_ranges(self):
        EbookLesson.objects.create(ebook=self.document, order=1, title="First", start_page=2)
        EbookLesson.objects.create(ebook=self.document, order=2, title="Second", start_page=5)

        result = sync_lessons_to_book_chapters(self.document, replace_existing=False)

        self.assertEqual(result.synced, 2)
        chapters = list(Chapter.objects.filter(book=self.book).order_by("order"))
        self.assertEqual([(item.title, item.start_page, item.end_page) for item in chapters], [("First", 2, 4), ("Second", 5, 8)])

    def test_existing_chapters_are_kept_without_replace(self):
        Chapter.objects.create(book=self.book, title="Manual", order=1, start_page=1)
        EbookLesson.objects.create(ebook=self.document, order=1, title="Generated", start_page=2)

        result = sync_lessons_to_book_chapters(self.document, replace_existing=False)

        self.assertEqual(result.synced, 0)
        self.assertEqual(Chapter.objects.get(book=self.book).title, "Manual")

    def test_existing_chapters_can_be_replaced_for_existing_books(self):
        Chapter.objects.create(book=self.book, title="Manual", order=1, start_page=1)
        EbookLesson.objects.create(ebook=self.document, order=1, title="Generated", start_page=2)

        result = sync_lessons_to_book_chapters(self.document, replace_existing=True)

        self.assertEqual(result.synced, 1)
        self.assertEqual(Chapter.objects.get(book=self.book).title, "Generated")

    def test_prepare_book_index_syncs_existing_mapped_lessons(self):
        self.document.toc_mode = EbookDocument.TocMode.NONE
        self.document.save()
        EbookLesson.objects.create(ebook=self.document, order=1, title="Ready lesson", start_page=3)

        result = prepare_book_index(self.book, replace_chapters=True)

        self.assertEqual(result.status, "ready")
        self.assertEqual(Chapter.objects.get(book=self.book).start_page, 3)
