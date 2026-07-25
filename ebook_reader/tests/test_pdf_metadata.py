import tempfile
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from ebook_reader.models import EbookDocument
from ebook_reader.services.pdf_metadata import EbookPdfError, inspect_pdf_metadata
from library.models import Book, Category


def blank_pdf_bytes(page_count=1):
    writer = PdfWriter()
    for _index in range(page_count):
        writer.add_blank_page(width=200, height=200)
    return write_pdf(writer)


def text_pdf_bytes():
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 72 Td (Hello ebook) Tj ET")
    page[NameObject("/Contents")] = stream
    return write_pdf(writer)


def outlined_pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_outline_item("First lesson", 0)
    return write_pdf(writer)


def encrypted_pdf_bytes():
    reader = PdfReader(BytesIO(blank_pdf_bytes()))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt("secret")
    return write_pdf(writer)


def write_pdf(writer):
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class EbookPdfMetadataTests(TestCase):
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

    def create_document(self, title="PDF Book", pdf_bytes=None, filename="book.pdf"):
        book = Book.objects.create(
            title=title,
            slug=title.lower().replace(" ", "-"),
            category=self.category,
        )
        if pdf_bytes is not None:
            book.pdf_file.save(filename, ContentFile(pdf_bytes), save=True)
        return EbookDocument.objects.create(book=book)

    def test_inspects_total_pages_from_existing_book_pdf(self):
        document = self.create_document(pdf_bytes=blank_pdf_bytes(page_count=2))

        metadata = inspect_pdf_metadata(document)

        self.assertEqual(metadata.total_pages, 2)
        self.assertFalse(metadata.has_embedded_text)
        self.assertFalse(metadata.has_bookmarks)
        self.assertEqual(metadata.book_id, document.book_id)

    def test_detects_embedded_text(self):
        document = self.create_document(pdf_bytes=text_pdf_bytes())

        metadata = inspect_pdf_metadata(document)

        self.assertTrue(metadata.has_embedded_text)

    def test_detects_bookmarks(self):
        document = self.create_document(pdf_bytes=outlined_pdf_bytes())

        metadata = inspect_pdf_metadata(document)

        self.assertTrue(metadata.has_bookmarks)

    def test_missing_pdf_returns_structured_error(self):
        document = self.create_document(pdf_bytes=None)

        with self.assertRaises(EbookPdfError) as context:
            inspect_pdf_metadata(document)

        self.assertEqual(context.exception.code, "missing_pdf")
        self.assertEqual(context.exception.ebook_id, document.id)

    def test_corrupt_pdf_returns_structured_error(self):
        document = self.create_document(pdf_bytes=b"this is not a pdf")

        with self.assertRaises(EbookPdfError) as context:
            inspect_pdf_metadata(document)

        self.assertEqual(context.exception.code, "corrupt_pdf")

    def test_empty_pdf_file_returns_structured_error(self):
        document = self.create_document(pdf_bytes=b"")

        with self.assertRaises(EbookPdfError) as context:
            inspect_pdf_metadata(document)

        self.assertEqual(context.exception.code, "empty_pdf")

    def test_zero_page_pdf_returns_structured_error(self):
        document = self.create_document(pdf_bytes=write_pdf(PdfWriter()))

        with self.assertRaises(EbookPdfError) as context:
            inspect_pdf_metadata(document)

        self.assertEqual(context.exception.code, "empty_pdf")

    def test_encrypted_pdf_returns_structured_error(self):
        document = self.create_document(pdf_bytes=encrypted_pdf_bytes())

        with self.assertRaises(EbookPdfError) as context:
            inspect_pdf_metadata(document)

        self.assertEqual(context.exception.code, "encrypted_pdf")

    def test_management_command_prints_metadata_without_changing_lessons(self):
        document = self.create_document(pdf_bytes=blank_pdf_bytes())
        output = BytesIO()
        text_output = TextOutput(output)

        call_command("inspect_ebook_pdf", document.id, stdout=text_output)

        self.assertIn('"total_pages": 1', output.getvalue().decode())
        self.assertEqual(document.lessons.count(), 0)

    def test_management_command_raises_command_error_for_invalid_pdf(self):
        document = self.create_document(pdf_bytes=b"invalid")

        with self.assertRaises(CommandError):
            call_command("inspect_ebook_pdf", document.id)


class TextOutput:
    def __init__(self, output):
        self.output = output

    def write(self, value):
        self.output.write(str(value).encode())
        self.output.write(b"\n")
