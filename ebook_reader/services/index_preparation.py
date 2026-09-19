from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ebook_reader.models import EbookDocument
from ebook_reader.services.index_sync import IndexSyncResult, sync_lessons_to_book_chapters
from ebook_reader.services.onboarding import create_ebook_document_for_book
from ebook_reader.services.pdf_metadata import EbookPdfError, inspect_pdf_metadata
from ebook_reader.services.toc_detection.admin_workflow import (
    accept_detected_toc_range,
    run_toc_detection,
)
from ebook_reader.services.toc_processing import TocProcessingResult, process_ebook_toc
from library.models import Book


@dataclass(frozen=True)
class IndexPreparationResult:
    book_id: int
    ebook_document_id: int | None = None
    status: str = "skipped"
    created_document: bool = False
    toc_detected: bool = False
    toc_range_accepted: bool = False
    page_mapping_accepted: bool = False
    toc_processing: dict | None = None
    chapter_sync: dict | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


def prepare_book_index(
    book: Book,
    *,
    replace_chapters: bool = False,
    force_toc: bool = False,
) -> IndexPreparationResult:
    if not book.pdf_file:
        return IndexPreparationResult(book_id=book.id, warnings=["Book has no PDF file."])

    try:
        ebook_document, created = create_ebook_document_for_book(book)
    except Exception as error:
        return IndexPreparationResult(
            book_id=book.id,
            status="failed",
            warnings=[str(error)],
        )
    if ebook_document is None:
        return IndexPreparationResult(book_id=book.id, warnings=["EbookDocument was not created."])

    warnings = []
    _inspect_document(ebook_document, warnings)
    ebook_document.refresh_from_db()

    toc_detected = False
    toc_range_accepted = False
    if ebook_document.toc_mode == EbookDocument.TocMode.MANUAL and ebook_document.toc_start_page and ebook_document.toc_end_page:
        toc_range_accepted = True
    elif ebook_document.toc_mode == EbookDocument.TocMode.AUTO:
        detection = run_toc_detection(EbookDocument.objects.filter(id=ebook_document.id))
        toc_detected = bool(detection.detected)
        ebook_document.refresh_from_db()
        if ebook_document.detected_toc_start_page and ebook_document.detected_toc_end_page:
            accepted = accept_detected_toc_range(EbookDocument.objects.filter(id=ebook_document.id))
            toc_range_accepted = bool(accepted.updated)
            ebook_document.refresh_from_db()
        if not toc_detected:
            warnings.append("TOC page range could not be detected automatically.")
    elif ebook_document.toc_mode == EbookDocument.TocMode.NONE:
        warnings.append("Book is configured as no TOC.")

    page_mapping_accepted = _accept_available_page_mapping(ebook_document)
    ebook_document.refresh_from_db()

    toc_result = None
    if toc_range_accepted or force_toc:
        toc_result = process_ebook_toc(ebook_document.id, force=force_toc)
        ebook_document.refresh_from_db()
        if toc_result.warnings:
            warnings.extend(toc_result.warnings)
    else:
        warnings.append("TOC processing skipped because no accepted TOC range is available.")

    sync_result = _sync_if_ready(ebook_document, replace_chapters=replace_chapters)
    if sync_result.warnings:
        warnings.extend(sync_result.warnings)

    status = "ready" if sync_result.synced else "review_required"
    if toc_result and toc_result.status == "failed":
        status = "failed"

    return IndexPreparationResult(
        book_id=book.id,
        ebook_document_id=ebook_document.id,
        status=status,
        created_document=created,
        toc_detected=toc_detected,
        toc_range_accepted=toc_range_accepted,
        page_mapping_accepted=page_mapping_accepted,
        toc_processing=toc_result.as_dict() if toc_result else None,
        chapter_sync=sync_result.as_dict(),
        warnings=warnings,
    )


def _inspect_document(ebook_document: EbookDocument, warnings: list[str]) -> None:
    try:
        metadata = inspect_pdf_metadata(ebook_document)
    except EbookPdfError as error:
        warnings.append(f"{error.code}: {error.message}")
        ebook_document.status = EbookDocument.Status.FAILED
        ebook_document.processing_error = f"{error.code}: {error.message}"
        ebook_document.save(update_fields=["status", "processing_error", "updated_at"])
        return
    ebook_document.total_pdf_pages = metadata.total_pages
    ebook_document.processing_metadata = metadata.as_dict()
    ebook_document.processing_error = ""
    ebook_document.status = EbookDocument.Status.REVIEW_REQUIRED
    ebook_document.save(
        update_fields=[
            "total_pdf_pages",
            "processing_metadata",
            "processing_error",
            "status",
            "updated_at",
        ]
    )


def _accept_available_page_mapping(ebook_document: EbookDocument) -> bool:
    if ebook_document.page_mapping_mode in (
        EbookDocument.PageMappingMode.MANUAL_OFFSET,
        EbookDocument.PageMappingMode.MANUAL_ANCHORS,
        EbookDocument.PageMappingMode.NONE,
    ):
        ebook_document.page_mapping_status = EbookDocument.PageMappingStatus.ACCEPTED
        ebook_document.save(update_fields=["page_mapping_status", "updated_at"])
        return True
    if ebook_document.detected_page_number_offset is None:
        return False
    ebook_document.page_mapping_mode = EbookDocument.PageMappingMode.MANUAL_OFFSET
    ebook_document.page_number_offset = ebook_document.detected_page_number_offset
    ebook_document.page_mapping_status = EbookDocument.PageMappingStatus.ACCEPTED
    ebook_document.save(
        update_fields=[
            "page_mapping_mode",
            "page_number_offset",
            "page_mapping_status",
            "updated_at",
        ]
    )
    return True


def _sync_if_ready(ebook_document: EbookDocument, *, replace_chapters: bool) -> IndexSyncResult:
    return sync_lessons_to_book_chapters(
        ebook_document,
        replace_existing=replace_chapters,
    )
