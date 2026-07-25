import logging
import os
import re
from dataclasses import dataclass

from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.utils.text import get_valid_filename

logger = logging.getLogger(__name__)

PDF_HEADER = b"%PDF-"
RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK_SIZE = 64 * 1024


class PdfDeliveryError(Exception):
    """Base exception for protected ebook PDF delivery errors."""


class PdfNotAvailable(PdfDeliveryError):
    pass


class PdfNotReadable(PdfDeliveryError):
    pass


class InvalidRange(PdfDeliveryError):
    pass


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self):
        return self.end - self.start + 1


def build_pdf_streaming_response(ebook_document, request, *, head_only=False):
    """Return an authenticated PDF response with HTTP byte-range support."""

    pdf_file = ebook_document.book.pdf_file
    if not pdf_file:
        logger.info("ebook_pdf_missing", extra={"ebook_document_id": ebook_document.id})
        raise Http404("PDF file is not available.")

    try:
        path = pdf_file.path
    except (NotImplementedError, AttributeError, ValueError) as exc:
        logger.warning(
            "ebook_pdf_storage_not_streamable",
            extra={"ebook_document_id": ebook_document.id},
            exc_info=exc,
        )
        return JsonResponse(
            {"detail": "PDF storage backend does not support local streaming yet."},
            status=501,
        )

    if not os.path.exists(path) or not os.path.isfile(path):
        logger.info(
            "ebook_pdf_file_not_found",
            extra={"ebook_document_id": ebook_document.id},
        )
        raise Http404("PDF file is not available.")

    file_size = os.path.getsize(path)
    if file_size <= 0:
        logger.info("ebook_pdf_empty", extra={"ebook_document_id": ebook_document.id})
        return JsonResponse({"detail": "PDF file is empty."}, status=422)

    range_header = request.headers.get("Range")
    try:
        byte_range = parse_range_header(range_header, file_size) if range_header else None
    except InvalidRange:
        logger.info(
            "ebook_pdf_invalid_range",
            extra={"ebook_document_id": ebook_document.id, "range": range_header},
        )
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{file_size}"
        response["Accept-Ranges"] = "bytes"
        return response

    file_obj = open(path, "rb")
    try:
        if not _has_valid_pdf_header(file_obj):
            file_obj.close()
            logger.info(
                "ebook_pdf_corrupt_header",
                extra={"ebook_document_id": ebook_document.id},
            )
            return JsonResponse({"detail": "PDF file is not readable."}, status=422)

        if byte_range:
            file_obj.seek(byte_range.start)
            response = _empty_response() if head_only else StreamingHttpResponse(
                _limited_file_iterator(file_obj, byte_range.length),
                status=206,
                content_type="application/pdf",
            )
            _set_common_pdf_headers(response, ebook_document, byte_range.length)
            response["Content-Range"] = (
                f"bytes {byte_range.start}-{byte_range.end}/{file_size}"
            )
            return response

        file_obj.seek(0)
        if head_only:
            file_obj.close()
            response = _empty_response()
        else:
            response = StreamingHttpResponse(
                _limited_file_iterator(file_obj, file_size),
                content_type="application/pdf",
            )
        _set_common_pdf_headers(response, ebook_document, file_size)
        return response
    except Exception:
        if not file_obj.closed:
            file_obj.close()
        raise


def parse_range_header(range_header, file_size):
    match = RANGE_PATTERN.match(range_header or "")
    if not match:
        raise InvalidRange()

    start_text, end_text = match.groups()
    if not start_text and not end_text:
        raise InvalidRange()

    if start_text:
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1
    else:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise InvalidRange()
        start = max(file_size - suffix_length, 0)
        end = file_size - 1

    if start >= file_size or end < start:
        raise InvalidRange()

    return ByteRange(start=start, end=min(end, file_size - 1))


def _has_valid_pdf_header(file_obj):
    file_obj.seek(0)
    header = file_obj.read(len(PDF_HEADER))
    return header == PDF_HEADER


def _limited_file_iterator(file_obj, length):
    return LimitedFileIterator(file_obj, length)


class LimitedFileIterator:
    def __init__(self, file_obj, length):
        self.file_obj = file_obj
        self.remaining = length

    def __iter__(self):
        return self

    def __next__(self):
        if self.remaining <= 0:
            self.file_obj.close()
            raise StopIteration
        chunk = self.file_obj.read(min(CHUNK_SIZE, self.remaining))
        if not chunk:
            self.file_obj.close()
            raise StopIteration
        self.remaining -= len(chunk)
        return chunk


def _empty_response():
    return HttpResponse(content=b"", content_type="application/pdf")


def _set_common_pdf_headers(response, ebook_document, content_length):
    filename = get_valid_filename(f"{ebook_document.book.title or 'ebook'}.pdf")
    response["Content-Type"] = "application/pdf"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Content-Length"] = str(content_length)
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, max-age=0, no-store"
