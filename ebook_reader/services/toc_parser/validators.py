from collections import Counter

from .confidence import mark_low_confidence
from .models import TocCandidate


def validate_candidates(
    candidates: list[TocCandidate],
    *,
    total_pdf_pages: int | None,
) -> tuple[list[TocCandidate], list[TocCandidate], dict[str, object]]:
    """Split candidates into valid/invalid and report sequence diagnostics."""
    duplicate_orders = _duplicate_orders(candidates)
    previous_order = None
    previous_page = None
    missing_serial_numbers = 0
    low_confidence_entries = 0

    for candidate in candidates:
        mark_low_confidence(candidate)
        if candidate.confidence < 0.55:
            low_confidence_entries += 1

        if candidate.order is None:
            missing_serial_numbers += 1
        elif candidate.order in duplicate_orders:
            candidate.validation_errors.append(f"Duplicate serial number: {candidate.order}.")
        elif previous_order is not None and candidate.order <= previous_order:
            candidate.warnings.append("Serial number is not increasing from the previous entry.")

        if candidate.printed_page_number is not None:
            if candidate.printed_page_number < 1:
                candidate.validation_errors.append("Printed page number must be greater than zero.")
            if total_pdf_pages and candidate.printed_page_number > total_pdf_pages * 3:
                candidate.warnings.append("Printed page number is unusually high for this PDF.")
            if previous_page is not None and candidate.printed_page_number < previous_page:
                candidate.warnings.append("Printed page number decreased from the previous entry.")
            previous_page = candidate.printed_page_number

        if not candidate.title.strip():
            candidate.validation_errors.append("Title is empty.")

        if candidate.order is not None:
            previous_order = candidate.order

    valid = [candidate for candidate in candidates if not candidate.validation_errors]
    invalid = [candidate for candidate in candidates if candidate.validation_errors]
    return (
        valid,
        invalid,
        {
            "duplicates": sorted(duplicate_orders),
            "missing_serial_numbers": missing_serial_numbers,
            "low_confidence_entries": low_confidence_entries,
        },
    )


def _duplicate_orders(candidates: list[TocCandidate]) -> set[int]:
    counts = Counter(candidate.order for candidate in candidates if candidate.order is not None)
    return {order for order, count in counts.items() if count > 1}
