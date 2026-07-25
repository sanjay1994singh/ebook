from io import BytesIO

from PIL import Image

from ebook_reader.services.ocr.exceptions import OcrDependencyError, OcrProcessingError
from ebook_reader.services.pdf_metadata import EbookPdfError


def render_pdf_page_to_image(ebook_document, page_number, *, dpi=300):
    if page_number < 1:
        raise OcrProcessingError("PDF page number must be 1-based and greater than zero.")

    try:
        import fitz
    except ImportError as error:
        raise OcrDependencyError("PyMuPDF is not installed.") from error

    pdf_bytes = _read_pdf_bytes(ebook_document)
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            if document.is_encrypted:
                raise EbookPdfError(
                    "encrypted_pdf",
                    "PDF is encrypted and cannot be rendered without a password.",
                    ebook_id=ebook_document.id,
                    book_id=ebook_document.book_id,
                )
            if page_number > document.page_count:
                raise OcrProcessingError(
                    "PDF page number is greater than total PDF pages.",
                    details={"page_number": page_number, "total_pages": document.page_count},
                )
            page = document.load_page(page_number - 1)
            zoom = dpi / 72
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            image = Image.open(BytesIO(pixmap.tobytes("png")))
            image.load()
            return image
    except EbookPdfError:
        raise
    except OcrProcessingError:
        raise
    except Exception as error:
        raise OcrProcessingError("PDF page could not be rendered.", details={"error": str(error)}) from error


def _read_pdf_bytes(ebook_document):
    pdf_file = ebook_document.book.pdf_file
    if not pdf_file:
        raise EbookPdfError(
            "missing_pdf",
            "The linked book does not have a PDF file.",
            ebook_id=ebook_document.id,
            book_id=ebook_document.book_id,
        )
    try:
        pdf_file.open("rb")
        return b"".join(pdf_file.chunks())
    except FileNotFoundError as error:
        raise EbookPdfError(
            "missing_pdf",
            "PDF file was referenced but could not be found in storage.",
            ebook_id=ebook_document.id,
            book_id=ebook_document.book_id,
        ) from error
    finally:
        try:
            pdf_file.close()
        except Exception:
            pass
