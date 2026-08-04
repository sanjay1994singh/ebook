from dataclasses import replace

from ebook_reader.models import EbookDocument
from ebook_reader.services.toc_parser.models import TocCandidate

from .anchors import PageMapper, build_mapper_for_document, result_from_manual_mapping
from .confidence import dominant_offset, score_offset
from .models import PageMappingResult, PageNumberSample
from .validators import validate_mapping_result, validate_samples


def estimate_page_mapping(
    ebook_document: EbookDocument,
    samples: list[PageNumberSample],
) -> PageMappingResult:
    """Estimate printed-page to physical-PDF mapping without saving anything."""
    manual_result = result_from_manual_mapping(ebook_document)
    if manual_result is not None:
        return validate_mapping_result(manual_result, ebook_document.total_pdf_pages)

    if not samples:
        return PageMappingResult(
            mapping_strategy="auto",
            warnings=["No page-number samples were supplied."],
            status="review_required",
        )

    warnings = validate_samples(samples, ebook_document.total_pdf_pages)
    usable_samples = [
        sample
        for sample in samples
        if sample.printed_page_number is not None and sample.printed_page_number > 0
    ]
    offset, conflicts = dominant_offset(usable_samples)
    if offset is None:
        return PageMappingResult(
            mapping_strategy="auto",
            warnings=warnings + ["No usable printed page numbers were detected."],
            status="review_required",
        )

    confidence, reasons = score_offset(usable_samples, offset, conflicts)
    agreeing = [sample for sample in usable_samples if sample.offset == offset]
    if conflicts:
        status = "review_required"
    elif len(agreeing) >= 2 and confidence >= 0.65:
        status = "detected"
    else:
        status = "review_required"

    evidence = reasons + [
        f"PDF page {sample.physical_pdf_page} showed printed page {sample.printed_page_number}."
        for sample in agreeing
    ]
    return PageMappingResult(
        mapping_strategy="auto",
        proposed_offset=offset if status == "detected" else None,
        confidence=confidence,
        evidence=evidence,
        conflicts=conflicts,
        warnings=warnings,
        status=status,
    )


def map_toc_candidates(
    candidates: list[TocCandidate],
    mapper_or_document: PageMapper | EbookDocument | PageMappingResult,
    *,
    total_pdf_pages: int | None = None,
) -> tuple[list[TocCandidate], list[str]]:
    """Return copies of TOC candidates with proposed physical PDF pages filled."""
    mapper = _coerce_mapper(mapper_or_document, total_pdf_pages)
    mapped_candidates = []
    warnings = []
    for candidate in candidates:
        pdf_page, candidate_warnings = mapper.map_printed_page(candidate.printed_page_number)
        updated_warnings = list(candidate.warnings) + candidate_warnings
        if candidate_warnings:
            warnings.extend(
                f"{candidate.title or candidate.raw_source_text}: {warning}"
                for warning in candidate_warnings
            )
        mapped_candidates.append(
            replace(
                candidate,
                proposed_pdf_page=pdf_page,
                warnings=updated_warnings,
            )
        )
    return mapped_candidates, warnings


def save_detected_mapping(ebook_document: EbookDocument, result: PageMappingResult) -> None:
    """Store detected mapping metadata without accepting it automatically."""
    ebook_document.detected_page_number_offset = result.proposed_offset
    ebook_document.page_mapping_confidence = result.confidence
    ebook_document.page_mapping_metadata = result.as_dict()
    ebook_document.page_mapping_status = (
        EbookDocument.PageMappingStatus.DETECTED
        if result.status == "detected"
        else EbookDocument.PageMappingStatus.REVIEW_REQUIRED
    )
    ebook_document.save(
        update_fields=[
            "detected_page_number_offset",
            "page_mapping_confidence",
            "page_mapping_metadata",
            "page_mapping_status",
            "updated_at",
        ]
    )


def _coerce_mapper(
    mapper_or_document: PageMapper | EbookDocument | PageMappingResult,
    total_pdf_pages: int | None,
) -> PageMapper:
    if isinstance(mapper_or_document, PageMapper):
        return mapper_or_document
    if isinstance(mapper_or_document, EbookDocument):
        return build_mapper_for_document(mapper_or_document)
    return PageMapper(
        mapper_or_document.mapping_strategy,
        mapper_or_document.proposed_offset,
        mapper_or_document.anchor_pairs,
        total_pdf_pages,
    )
