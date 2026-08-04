import logging

from celery import shared_task
from django.db import DatabaseError, transaction

from ebook_reader.models import Book, EbookDocument
from ebook_reader.services.feature_flags import processing_globally_enabled
from ebook_reader.services.pdf_metadata import EbookPdfError, inspect_pdf_metadata
from ebook_reader.services.toc_detection.admin_workflow import run_toc_detection
from ebook_reader.utils import extract_book_pages


logger = logging.getLogger(__name__)

TRANSIENT_PDF_ERROR_CODES = {"pdf_read_error"}


@shared_task(
    bind=True,
    autoretry_for=(DatabaseError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_uploaded_book(self, book_id, force_ocr=None):
    book = _claim_book_for_processing(book_id)
    if book is None and not Book.objects.filter(pk=book_id).exists():
        return {"status": "missing_book", "book_id": book_id}
    if book is None:
        return {"status": "skipped", "book_id": book_id, "reason": "already_processing"}
    try:
        page_count = extract_book_pages(book, force_ocr=force_ocr)
    except DatabaseError:
        raise
    except Exception as error:
        logger.exception("ebook.line_reader.processing_failed", extra={"book_id": book_id})
        return {"status": "failed", "book_id": book_id, "error": str(error)}
    return {"status": "ready", "book_id": book_id, "page_count": page_count}


def _claim_book_for_processing(book_id):
    with transaction.atomic():
        book = Book.objects.select_for_update().filter(pk=book_id).first()
        if book is None:
            return None
        if book.processing_status == Book.ProcessingStatus.PROCESSING:
            return None
        book.processing_status = Book.ProcessingStatus.PROCESSING
        book.processed_pages = 0
        book.processing_error = ""
        book.processed_at = None
        book.save(
            update_fields=(
                "processing_status",
                "processed_pages",
                "processing_error",
                "processed_at",
            )
        )
        return book


@shared_task(
    bind=True,
    autoretry_for=(DatabaseError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def inspect_ebook_document(self, ebook_document_id):
    if not processing_globally_enabled():
        logger.warning(
            "ebook.inspect.skipped",
            extra={"ebook_document_id": ebook_document_id, "reason": "processing_disabled"},
        )
        return {"status": "skipped", "reason": "processing_disabled"}

    logger.info("ebook.inspect.started", extra={"ebook_document_id": ebook_document_id})
    claimed = _claim_document_for_processing(ebook_document_id)
    if not claimed:
        logger.info(
            "ebook.inspect.skipped",
            extra={"ebook_document_id": ebook_document_id, "reason": "already_processing"},
        )
        return {"status": "skipped", "reason": "already_processing"}

    try:
        ebook_document = EbookDocument.objects.select_related("book").get(
            id=ebook_document_id
        )
        metadata = inspect_pdf_metadata(ebook_document)
    except EbookPdfError as error:
        if (
            error.code in TRANSIENT_PDF_ERROR_CODES
            and self.request.retries < self.max_retries
        ):
            logger.warning(
                "ebook.inspect.transient_error",
                extra={
                    "ebook_document_id": ebook_document_id,
                    "error_code": error.code,
                },
            )
            raise self.retry(exc=error, countdown=30, max_retries=3)

        _mark_failed(ebook_document_id, error.code, error.message)
        logger.warning(
            "ebook.inspect.failed",
            extra={"ebook_document_id": ebook_document_id, "error_code": error.code},
        )
        return {"status": "failed", "error_code": error.code}
    except EbookDocument.DoesNotExist:
        logger.warning(
            "ebook.inspect.missing_document",
            extra={"ebook_document_id": ebook_document_id},
        )
        return {"status": "missing_document"}
    except Exception as error:
        _mark_failed(ebook_document_id, "unexpected_error", "Unexpected PDF inspection error.")
        logger.exception(
            "ebook.inspect.unexpected_error",
            extra={"ebook_document_id": ebook_document_id},
        )
        raise error

    final_status = _status_for_metadata(metadata)
    EbookDocument.objects.filter(id=ebook_document_id).update(
        status=final_status,
        total_pdf_pages=metadata.total_pages,
        processing_error="",
        processing_metadata=metadata.as_dict(),
    )
    logger.info(
        "ebook.inspect.completed",
        extra={
            "ebook_document_id": ebook_document_id,
            "total_pdf_pages": metadata.total_pages,
            "final_status": final_status,
        },
    )
    return {
        "status": "completed",
        "ebook_document_id": ebook_document_id,
        "final_status": final_status,
        "total_pdf_pages": metadata.total_pages,
    }


def _claim_document_for_processing(ebook_document_id):
    with transaction.atomic():
        ebook_document = (
            EbookDocument.objects.select_for_update()
            .filter(id=ebook_document_id)
            .first()
        )
        if ebook_document is None:
            return True
        if ebook_document.status == EbookDocument.Status.PROCESSING:
            return False
        ebook_document.status = EbookDocument.Status.PROCESSING
        ebook_document.processing_error = ""
        ebook_document.save(update_fields=["status", "processing_error", "updated_at"])
    return True


def _status_for_metadata(metadata):
    if metadata.has_embedded_text or metadata.has_bookmarks:
        return EbookDocument.Status.REVIEW_REQUIRED
    return EbookDocument.Status.PENDING


def _mark_failed(ebook_document_id, error_code, message):
    EbookDocument.objects.filter(id=ebook_document_id).update(
        status=EbookDocument.Status.FAILED,
        processing_error=f"{error_code}: {message}",
    )


@shared_task(
    bind=True,
    autoretry_for=(DatabaseError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def detect_ebook_toc_document(self, ebook_document_id):
    if not processing_globally_enabled():
        logger.warning(
            "ebook.toc_detection.skipped",
            extra={"ebook_document_id": ebook_document_id, "reason": "processing_disabled"},
        )
        return {"status": "skipped", "reason": "processing_disabled"}

    logger.info("ebook.toc_detection.started", extra={"ebook_document_id": ebook_document_id})
    try:
        queryset = EbookDocument.objects.filter(id=ebook_document_id)
        if not queryset.exists():
            logger.warning(
                "ebook.toc_detection.missing_document",
                extra={"ebook_document_id": ebook_document_id},
            )
            return {"status": "missing_document"}
        result = run_toc_detection(queryset)
    except Exception as error:
        logger.exception(
            "ebook.toc_detection.unexpected_error",
            extra={"ebook_document_id": ebook_document_id},
        )
        raise error

    status = "completed" if result.detected else "review_required"
    logger.info(
        "ebook.toc_detection.completed",
        extra={
            "ebook_document_id": ebook_document_id,
            "detected": result.detected,
            "failed": result.failed,
            "skipped": result.skipped,
        },
    )
    return {
        "status": status,
        "ebook_document_id": ebook_document_id,
        "detected": result.detected,
        "failed": result.failed,
        "skipped": result.skipped,
    }
