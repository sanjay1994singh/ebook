from dataclasses import asdict, dataclass
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import EmptyFileError, FileNotDecryptedError, PdfReadError, PyPdfError


class EbookPdfError(Exception):
    def __init__(self, code, message, *, ebook_id=None, book_id=None):
        self.code = code
        self.message = message
        self.ebook_id = ebook_id
        self.book_id = book_id
        super().__init__(message)

    def as_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "ebook_id": self.ebook_id,
            "book_id": self.book_id,
        }


@dataclass(frozen=True)
class EbookPdfMetadata:
    ebook_id: int
    book_id: int
    book_title: str
    file_name: str
    total_pages: int
    has_embedded_text: bool
    has_bookmarks: bool
    is_encrypted: bool

    def as_dict(self):
        return asdict(self)


def inspect_pdf_metadata(ebook_document):
    pdf_file, reader = open_pdf_reader(ebook_document)

    if reader.is_encrypted:
        raise EbookPdfError(
            "encrypted_pdf",
            "PDF is encrypted and cannot be inspected without a password.",
            ebook_id=ebook_document.id,
            book_id=ebook_document.book_id,
        )

    try:
        total_pages = len(reader.pages)
    except FileNotDecryptedError as error:
        raise EbookPdfError(
            "encrypted_pdf",
            "PDF is encrypted and cannot be inspected without a password.",
            ebook_id=ebook_document.id,
            book_id=ebook_document.book_id,
        ) from error
    except PyPdfError as error:
        raise EbookPdfError(
            "corrupt_pdf",
            "PDF pages could not be read.",
            ebook_id=ebook_document.id,
            book_id=ebook_document.book_id,
        ) from error

    if total_pages < 1:
        raise EbookPdfError(
            "empty_pdf",
            "PDF has no pages.",
            ebook_id=ebook_document.id,
            book_id=ebook_document.book_id,
        )

    return EbookPdfMetadata(
        ebook_id=ebook_document.id,
        book_id=ebook_document.book_id,
        book_title=ebook_document.book.title,
        file_name=pdf_file.name,
        total_pages=total_pages,
        has_embedded_text=_has_embedded_text(reader),
        has_bookmarks=_has_bookmarks(reader),
        is_encrypted=False,
    )


def open_pdf_reader(ebook_document):
    pdf_file = _get_pdf_file(ebook_document)
    pdf_stream = _read_pdf_to_memory(pdf_file, ebook_document)
    reader = _open_reader(pdf_stream, ebook_document)
    return pdf_file, reader


def _get_pdf_file(ebook_document):
    book = ebook_document.book
    if not book.pdf_file:
        raise EbookPdfError(
            "missing_pdf",
            "The linked book does not have a PDF file.",
            ebook_id=ebook_document.id,
            book_id=book.id,
        )
    return book.pdf_file


def _read_pdf_to_memory(pdf_file, ebook_document):
    buffer = BytesIO()
    try:
        pdf_file.open("rb")
        for chunk in pdf_file.chunks():
            buffer.write(chunk)
    except FileNotFoundError as error:
        raise EbookPdfError(
            "missing_pdf",
            "PDF file was referenced but could not be found in storage.",
            ebook_id=ebook_document.id,
            book_id=ebook_document.book_id,
        ) from error
    except OSError as error:
        raise EbookPdfError(
            "pdf_read_error",
            "PDF file could not be opened from storage.",
            ebook_id=ebook_document.id,
            book_id=ebook_document.book_id,
        ) from error
    finally:
        try:
            pdf_file.close()
        except Exception:
            pass

    if buffer.tell() == 0:
        raise EbookPdfError(
            "empty_pdf",
            "PDF file is empty.",
            ebook_id=ebook_document.id,
            book_id=ebook_document.book_id,
        )

    buffer.seek(0)
    return buffer


def _open_reader(pdf_stream, ebook_document):
    try:
        return PdfReader(pdf_stream)
    except EmptyFileError as error:
        raise EbookPdfError(
            "empty_pdf",
            "PDF file is empty.",
            ebook_id=ebook_document.id,
            book_id=ebook_document.book_id,
        ) from error
    except PdfReadError as error:
        raise EbookPdfError(
            "corrupt_pdf",
            "PDF file is not a readable PDF.",
            ebook_id=ebook_document.id,
            book_id=ebook_document.book_id,
        ) from error


def _has_embedded_text(reader):
    for page in reader.pages:
        try:
            if (page.extract_text() or "").strip():
                return True
        except PyPdfError:
            continue
    return False


def _has_bookmarks(reader):
    try:
        return bool(reader.outline)
    except PyPdfError:
        return False
