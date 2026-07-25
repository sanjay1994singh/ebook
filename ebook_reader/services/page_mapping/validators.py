from .exceptions import PageMappingValidationError
from .models import PageMappingAnchorPair, PageMappingResult, PageNumberSample


def validate_samples(samples: list[PageNumberSample], total_pdf_pages: int | None) -> list[str]:
    warnings = []
    for sample in samples:
        if sample.physical_pdf_page < 1:
            raise PageMappingValidationError("Physical PDF pages must be 1-based.")
        if total_pdf_pages and sample.physical_pdf_page > total_pdf_pages:
            raise PageMappingValidationError("Sample physical page exceeds total PDF pages.")
        if sample.printed_page_number is None:
            warnings.append(f"PDF page {sample.physical_pdf_page} has no readable printed page number.")
        elif sample.printed_page_number < 1:
            warnings.append(f"PDF page {sample.physical_pdf_page} has an invalid printed page number.")
    return warnings


def validate_mapped_page(printed_page_number: int, pdf_page: int, total_pdf_pages: int | None) -> list[str]:
    warnings = []
    if printed_page_number < 1:
        warnings.append("Printed page number must be greater than zero.")
    if pdf_page < 1:
        warnings.append("Mapped PDF page is before the beginning of the PDF.")
    if total_pdf_pages and pdf_page > total_pdf_pages:
        warnings.append("Mapped PDF page is outside the PDF page count.")
    return warnings


def validate_mapping_result(result: PageMappingResult, total_pdf_pages: int | None) -> PageMappingResult:
    warnings = list(result.warnings)
    for anchor in result.anchor_pairs:
        warnings.extend(_validate_anchor(anchor, total_pdf_pages))
    return PageMappingResult(
        mapping_strategy=result.mapping_strategy,
        proposed_offset=result.proposed_offset,
        anchor_pairs=result.anchor_pairs,
        confidence=result.confidence,
        evidence=result.evidence,
        conflicts=result.conflicts,
        warnings=warnings,
        unmappable_candidates=result.unmappable_candidates,
        status=result.status,
    )


def _validate_anchor(anchor: PageMappingAnchorPair, total_pdf_pages: int | None) -> list[str]:
    warnings = []
    if anchor.printed_page_number < 1:
        warnings.append("Anchor printed page must be greater than zero.")
    if anchor.physical_pdf_page < 1:
        warnings.append("Anchor physical page must be greater than zero.")
    if total_pdf_pages and anchor.physical_pdf_page > total_pdf_pages:
        warnings.append("Anchor physical page exceeds total PDF pages.")
    return warnings
