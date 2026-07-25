import logging
from dataclasses import asdict, dataclass

from django.db import transaction
from django.utils import timezone
from pypdf.errors import PyPdfError

from ebook_reader.models import (
    EbookDocument,
    EbookLesson,
    EbookProcessingRun,
    EbookTocCandidate,
)
from ebook_reader.services.page_mapping import map_toc_candidates
from ebook_reader.services.feature_flags import processing_globally_enabled
from ebook_reader.services.pdf_metadata import EbookPdfError, open_pdf_reader
from ebook_reader.services.toc_parser import parse_toc, resolve_effective_toc_range
from ebook_reader.services.toc_parser.exceptions import EffectiveTocRangeError
from ebook_reader.services.toc_parser.models import TocPageInput, TocParserInput


PARSER_VERSION = "toc_parser.v1"
EXTRACTION_ENGINE = "embedded_text"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TocProcessingResult:
    ebook_document_id: int
    processing_run_id: int | None
    status: str
    dry_run: bool = False
    valid_count: int = 0
    invalid_count: int = 0
    unclassified_count: int = 0
    created_lessons: int = 0
    skipped_lessons: int = 0
    warnings: list[str] | None = None
    diagnostics: dict | None = None

    def as_dict(self):
        return asdict(self)


def process_ebook_toc(ebook_document_id: int, *, force: bool = False, dry_run: bool = False):
    """Extract, parse, map and persist draft ebook lessons for one document."""
    if not dry_run and not processing_globally_enabled():
        return TocProcessingResult(
            ebook_document_id=ebook_document_id,
            processing_run_id=None,
            status="skipped",
            warnings=["Ebook processing is disabled by feature flag."],
        )
    if dry_run:
        return _process_dry_run(ebook_document_id, force=force)

    claim = _claim_processing_run(ebook_document_id)
    if claim.status != "processing":
        return claim

    run = EbookProcessingRun.objects.get(id=claim.processing_run_id)
    try:
        ebook_document = EbookDocument.objects.select_related("book").get(
            id=ebook_document_id
        )
        if ebook_document.toc_mode == EbookDocument.TocMode.NONE:
            return _finish_skipped(
                run,
                ebook_document,
                "EbookDocument is configured as no TOC.",
                dry_run=dry_run,
            )

        start_page, end_page, range_warnings = resolve_effective_toc_range(ebook_document)
        if not start_page or not end_page:
            return _finish_review_required(
                run,
                ebook_document,
                range_warnings + ["TOC processing skipped because no accepted range exists."],
                dry_run=dry_run,
            )

        pages, extraction_warnings = _extract_toc_pages(
            ebook_document,
            start_page,
            end_page,
        )
        parser_input = TocParserInput(
            ebook_document_id=ebook_document.id,
            effective_toc_start_page=start_page,
            effective_toc_end_page=end_page,
            total_pdf_pages=ebook_document.total_pdf_pages,
            pages=pages,
            extraction_warnings=range_warnings + extraction_warnings,
        )
        parsing_result = parse_toc(parser_input)
        mapped_valid, mapping_warnings = map_toc_candidates(
            parsing_result.valid_candidates,
            ebook_document,
        )
        mapped_invalid, invalid_mapping_warnings = map_toc_candidates(
            parsing_result.invalid_candidates,
            ebook_document,
        )
        diagnostics = {
            "toc_range": {"start": start_page, "end": end_page},
            "parser": parsing_result.as_dict(),
            "mapping_warnings": mapping_warnings + invalid_mapping_warnings,
            "force": force,
            "dry_run": dry_run,
        }
        return _persist_processing_result(
            run.id,
            ebook_document.id,
            mapped_valid,
            mapped_invalid,
            parsing_result.unclassified_rows,
            diagnostics,
            force=force,
        )
    except Exception as error:
        return _finish_failed(run, ebook_document_id, error)


def _process_dry_run(ebook_document_id, *, force):
    ebook_document = EbookDocument.objects.select_related("book").get(id=ebook_document_id)
    if ebook_document.toc_mode == EbookDocument.TocMode.NONE:
        return TocProcessingResult(
            ebook_document_id=ebook_document_id,
            processing_run_id=None,
            status="skipped",
            dry_run=True,
            warnings=["EbookDocument is configured as no TOC."],
        )
    start_page, end_page, range_warnings = resolve_effective_toc_range(ebook_document)
    if not start_page or not end_page:
        return TocProcessingResult(
            ebook_document_id=ebook_document_id,
            processing_run_id=None,
            status="review_required",
            dry_run=True,
            warnings=range_warnings
            + ["TOC processing skipped because no accepted range exists."],
        )
    pages, extraction_warnings = _extract_toc_pages(ebook_document, start_page, end_page)
    parser_input = TocParserInput(
        ebook_document_id=ebook_document.id,
        effective_toc_start_page=start_page,
        effective_toc_end_page=end_page,
        total_pdf_pages=ebook_document.total_pdf_pages,
        pages=pages,
        extraction_warnings=range_warnings + extraction_warnings,
    )
    parsing_result = parse_toc(parser_input)
    mapped_valid, mapping_warnings = map_toc_candidates(
        parsing_result.valid_candidates,
        ebook_document,
    )
    mapped_invalid, invalid_mapping_warnings = map_toc_candidates(
        parsing_result.invalid_candidates,
        ebook_document,
    )
    diagnostics = {
        "toc_range": {"start": start_page, "end": end_page},
        "parser": parsing_result.as_dict(),
        "mapping_warnings": mapping_warnings + invalid_mapping_warnings,
        "force": force,
        "dry_run": True,
    }
    return TocProcessingResult(
        ebook_document_id=ebook_document.id,
        processing_run_id=None,
        status="dry_run",
        dry_run=True,
        valid_count=len(mapped_valid),
        invalid_count=len(mapped_invalid),
        unclassified_count=len(parsing_result.unclassified_rows),
        diagnostics=diagnostics,
    )


def _claim_processing_run(ebook_document_id):
    with transaction.atomic():
        ebook_document = (
            EbookDocument.objects.select_for_update()
            .select_related("book")
            .get(id=ebook_document_id)
        )
        if ebook_document.status == EbookDocument.Status.PROCESSING:
            return TocProcessingResult(
                ebook_document_id=ebook_document_id,
                processing_run_id=None,
                status="skipped",
                warnings=["EbookDocument is already processing."],
            )
        run = EbookProcessingRun.objects.create(
            ebook_document=ebook_document,
            status=EbookProcessingRun.Status.PROCESSING,
            extraction_engine=EXTRACTION_ENGINE,
            parser_version=PARSER_VERSION,
        )
        ebook_document.status = EbookDocument.Status.PROCESSING
        ebook_document.processing_error = ""
        ebook_document.save(update_fields=["status", "processing_error", "updated_at"])
        return TocProcessingResult(
            ebook_document_id=ebook_document_id,
            processing_run_id=run.id,
            status="processing",
        )


def _extract_toc_pages(ebook_document, start_page, end_page):
    _pdf_file, reader = open_pdf_reader(ebook_document)
    total_pages = len(reader.pages)
    if end_page > total_pages:
        raise EffectiveTocRangeError("Accepted TOC range exceeds physical PDF pages.")

    pages = []
    warnings = []
    for page_number in range(start_page, end_page + 1):
        try:
            text = reader.pages[page_number - 1].extract_text() or ""
        except PyPdfError as error:
            text = ""
            warnings.append(f"PDF page {page_number} embedded text extraction failed: {error}")
        pages.append(TocPageInput(page_number=page_number, embedded_text=text))
    return pages, warnings


def _persist_processing_result(
    run_id,
    ebook_document_id,
    valid_candidates,
    invalid_candidates,
    unclassified_rows,
    diagnostics,
    *,
    force,
):
    with transaction.atomic():
        ebook_document = EbookDocument.objects.select_for_update().get(
            id=ebook_document_id
        )
        run = EbookProcessingRun.objects.select_for_update().get(id=run_id)
        protected_lessons = ebook_document.lessons.filter(
            is_verified=True
        ) | ebook_document.lessons.filter(is_manually_edited=True)
        protected_snapshot = [_lesson_snapshot(item) for item in protected_lessons]
        if protected_snapshot and not force:
            diagnostics["protected_lessons"] = protected_snapshot
            _complete_run(
                run,
                status=EbookProcessingRun.Status.COMPLETED,
                valid_count=len(valid_candidates),
                invalid_count=len(invalid_candidates),
                unclassified_count=len(unclassified_rows),
                diagnostics=diagnostics,
            )
            ebook_document.status = EbookDocument.Status.REVIEW_REQUIRED
            ebook_document.processing_metadata = diagnostics
            ebook_document.save(update_fields=["status", "processing_metadata", "updated_at"])
            return TocProcessingResult(
                ebook_document_id=ebook_document_id,
                processing_run_id=run.id,
                status="review_required",
                valid_count=len(valid_candidates),
                invalid_count=len(invalid_candidates),
                unclassified_count=len(unclassified_rows),
                created_lessons=0,
                skipped_lessons=len(valid_candidates),
                warnings=["Verified or manually edited lessons are protected. Use force to replace them."],
                diagnostics=diagnostics,
            )

        if force:
            diagnostics["force_audit_snapshot"] = [
                _lesson_snapshot(item) for item in ebook_document.lessons.all()
            ]
            ebook_document.lessons.all().delete()
            ebook_document.toc_candidates.all().delete()
        else:
            ebook_document.lessons.filter(
                is_verified=False,
                is_manually_edited=False,
            ).delete()
            ebook_document.toc_candidates.all().delete()

        created_lessons = _create_lessons(ebook_document, run, valid_candidates)
        _create_invalid_candidates(
            ebook_document,
            run,
            invalid_candidates,
            unclassified_rows,
        )
        _complete_run(
            run,
            status=EbookProcessingRun.Status.COMPLETED,
            valid_count=len(valid_candidates),
            invalid_count=len(invalid_candidates),
            unclassified_count=len(unclassified_rows),
            diagnostics=diagnostics,
            mapping_strategy=_mapping_strategy_for(ebook_document),
        )
        ebook_document.status = EbookDocument.Status.REVIEW_REQUIRED
        ebook_document.processing_metadata = diagnostics
        ebook_document.processing_error = ""
        ebook_document.save(
            update_fields=[
                "status",
                "processing_metadata",
                "processing_error",
                "updated_at",
            ]
        )
        return TocProcessingResult(
            ebook_document_id=ebook_document_id,
            processing_run_id=run.id,
            status="review_required",
            valid_count=len(valid_candidates),
            invalid_count=len(invalid_candidates),
            unclassified_count=len(unclassified_rows),
            created_lessons=created_lessons,
            diagnostics=diagnostics,
        )


def _create_lessons(ebook_document, run, candidates):
    lessons = []
    for index, candidate in enumerate(candidates, start=1):
        lessons.append(
            EbookLesson(
                ebook=ebook_document,
                processing_run=run,
                order=candidate.order or index,
                title=candidate.title,
                printed_page_number=candidate.printed_page_number,
                start_page=candidate.proposed_pdf_page,
                source_toc_page=candidate.source_toc_page,
                confidence=candidate.confidence,
                parser_strategy=candidate.parser_strategy,
                raw_ocr_text=candidate.raw_source_text,
                warnings=candidate.warnings,
                is_verified=False,
                is_manually_edited=False,
            )
        )
    EbookLesson.objects.bulk_create(lessons)
    return len(lessons)


def _create_invalid_candidates(ebook_document, run, invalid_candidates, unclassified_rows):
    records = []
    for candidate in invalid_candidates:
        records.append(
            EbookTocCandidate(
                ebook_document=ebook_document,
                processing_run=run,
                candidate_type=EbookTocCandidate.CandidateType.INVALID,
                order=candidate.order,
                title=candidate.title,
                printed_page_number=candidate.printed_page_number,
                proposed_pdf_page=candidate.proposed_pdf_page,
                source_toc_page=candidate.source_toc_page,
                parser_strategy=candidate.parser_strategy,
                raw_source_text=candidate.raw_source_text,
                confidence=candidate.confidence,
                warnings=candidate.warnings,
                validation_errors=candidate.validation_errors,
                diagnostics={"confidence_reasons": candidate.confidence_reasons},
            )
        )
    for row in unclassified_rows:
        records.append(
            EbookTocCandidate(
                ebook_document=ebook_document,
                processing_run=run,
                candidate_type=EbookTocCandidate.CandidateType.UNCLASSIFIED,
                source_toc_page=row.source_toc_page,
                raw_source_text=row.raw_source_text or row.text,
                warnings=row.warnings,
                diagnostics=row.as_dict(),
            )
        )
    EbookTocCandidate.objects.bulk_create(records)


def _finish_skipped(run, ebook_document, message, *, dry_run):
    _complete_run(
        run,
        status=EbookProcessingRun.Status.SKIPPED,
        diagnostics={"warnings": [message], "dry_run": dry_run},
    )
    ebook_document.status = EbookDocument.Status.PENDING
    ebook_document.processing_metadata = {"warnings": [message]}
    ebook_document.save(update_fields=["status", "processing_metadata", "updated_at"])
    return TocProcessingResult(
        ebook_document_id=ebook_document.id,
        processing_run_id=run.id,
        status="skipped",
        dry_run=dry_run,
        warnings=[message],
    )


def _finish_review_required(run, ebook_document, warnings, *, dry_run):
    _complete_run(
        run,
        status=EbookProcessingRun.Status.SKIPPED,
        diagnostics={"warnings": warnings, "dry_run": dry_run},
    )
    ebook_document.status = EbookDocument.Status.REVIEW_REQUIRED
    ebook_document.processing_metadata = {"warnings": warnings}
    ebook_document.save(update_fields=["status", "processing_metadata", "updated_at"])
    return TocProcessingResult(
        ebook_document_id=ebook_document.id,
        processing_run_id=run.id,
        status="review_required",
        dry_run=dry_run,
        warnings=warnings,
    )


def _finish_failed(run, ebook_document_id, error):
    safe_message = _safe_error(error)
    with transaction.atomic():
        locked_run = EbookProcessingRun.objects.select_for_update().get(id=run.id)
        _complete_run(
            locked_run,
            status=EbookProcessingRun.Status.FAILED,
            diagnostics={"error": safe_message},
            error_message=safe_message,
        )
        EbookDocument.objects.filter(id=ebook_document_id).update(
            status=EbookDocument.Status.FAILED,
            processing_error=safe_message,
        )
    return TocProcessingResult(
        ebook_document_id=ebook_document_id,
        processing_run_id=run.id,
        status="failed",
        warnings=[safe_message],
    )


def _complete_run(
    run,
    *,
    status,
    valid_count=0,
    invalid_count=0,
    unclassified_count=0,
    diagnostics=None,
    error_message="",
    mapping_strategy="",
):
    run.status = status
    run.completed_at = timezone.now()
    run.valid_count = valid_count
    run.invalid_count = invalid_count
    run.unclassified_count = unclassified_count
    run.diagnostics = diagnostics or {}
    run.error_message = error_message
    run.mapping_strategy = mapping_strategy
    run.save(
        update_fields=[
            "status",
            "completed_at",
            "valid_count",
            "invalid_count",
            "unclassified_count",
            "diagnostics",
            "error_message",
            "mapping_strategy",
        ]
    )
    logger.info(
        "ebook.toc_processing.completed",
        extra={
            "ebook_document_id": run.ebook_document_id,
            "processing_run_id": run.id,
            "status": status,
            "parser_version": run.parser_version,
            "mapping_strategy": mapping_strategy,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "unclassified_count": unclassified_count,
        },
    )


def _lesson_snapshot(lesson):
    return {
        "id": lesson.id,
        "order": lesson.order,
        "title": lesson.title,
        "printed_page_number": lesson.printed_page_number,
        "start_page": lesson.start_page,
        "end_page": lesson.end_page,
        "is_verified": lesson.is_verified,
        "is_manually_edited": lesson.is_manually_edited,
    }


def _mapping_strategy_for(ebook_document):
    if ebook_document.page_mapping_mode != EbookDocument.PageMappingMode.AUTO:
        return ebook_document.page_mapping_mode
    if ebook_document.page_mapping_status == EbookDocument.PageMappingStatus.ACCEPTED:
        return "accepted_offset"
    if ebook_document.detected_page_number_offset is not None:
        return "detected_offset"
    return "none"


def _safe_error(error):
    if isinstance(error, EbookPdfError):
        return f"{error.code}: {error.message}"
    return str(error)[:500]
