from .exceptions import EffectiveTocRangeError
from .models import PageDiagnostics, TocParserInput, TocParsingResult
from .normalisation import looks_like_garbled_text
from .row_grouper import filter_repeated_headers_and_footers, rows_from_page
from .strategies import ReviewOnlyFallbackStrategy, choose_strategy
from .validators import validate_candidates


def resolve_effective_toc_range(ebook_document) -> tuple[int | None, int | None, list[str]]:
    """Return the accepted TOC range without detecting or guessing one."""
    warnings: list[str] = []
    if ebook_document.toc_mode == ebook_document.TocMode.NONE:
        warnings.append("EbookDocument is configured as no TOC.")
        return None, None, warnings
    if ebook_document.toc_mode == ebook_document.TocMode.MANUAL:
        return ebook_document.toc_start_page, ebook_document.toc_end_page, warnings
    if ebook_document.detected_toc_start_page and ebook_document.detected_toc_end_page:
        warnings.append("Using accepted auto-detected TOC range from EbookDocument.")
        return ebook_document.detected_toc_start_page, ebook_document.detected_toc_end_page, warnings
    warnings.append("No accepted TOC range is available; review is required.")
    return None, None, warnings


def parse_toc(parser_input: TocParserInput) -> TocParsingResult:
    """Parse an already accepted TOC range into explainable lesson candidates."""
    if parser_input.effective_toc_start_page is None or parser_input.effective_toc_end_page is None:
        return TocParsingResult(
            parser_warnings=parser_input.extraction_warnings
            + ["No valid effective TOC range was supplied to the parser."],
            requires_review=True,
            no_toc=True,
        )
    _validate_range(parser_input)

    pages = [
        page
        for page in parser_input.pages
        if parser_input.effective_toc_start_page <= page.page_number <= parser_input.effective_toc_end_page
    ]
    skipped_pages = len(parser_input.pages) - len(pages)
    page_rows = {page.page_number: rows_from_page(page) for page in pages}
    filtered_page_rows = filter_repeated_headers_and_footers(page_rows)
    candidates = []
    unclassified = []
    diagnostics = []

    for page in pages:
        all_rows = page_rows.get(page.page_number, [])
        rows = filtered_page_rows.get(page.page_number, [])
        warnings = list(page.warnings)
        if page.embedded_text and looks_like_garbled_text(page.embedded_text) and page.ocr_words:
            warnings.append("Embedded text looked garbled; OCR words were preferred.")

        strategy = choose_strategy(page, rows)
        page_candidates, page_unclassified = strategy.parse_page(page, rows)
        if not page_candidates and rows:
            fallback = ReviewOnlyFallbackStrategy()
            page_candidates, page_unclassified = fallback.parse_page(page, rows)
            strategy_name = fallback.name
        else:
            strategy_name = strategy.name

        candidates.extend(page_candidates)
        unclassified.extend(page_unclassified)
        diagnostics.append(
            PageDiagnostics(
                page_number=page.page_number,
                strategy_name=strategy_name,
                rows_seen=len(all_rows),
                rows_filtered=len(all_rows) - len(rows),
                warnings=warnings,
                evidence=[f"{len(page_candidates)} candidate(s) parsed from page."],
            )
        )

    valid, invalid, validation_summary = validate_candidates(
        candidates,
        total_pdf_pages=parser_input.total_pdf_pages,
    )
    result = TocParsingResult(
        valid_candidates=valid,
        invalid_candidates=invalid,
        unclassified_rows=unclassified,
        total_detected=len(candidates),
        duplicates=validation_summary["duplicates"],
        missing_serial_numbers=validation_summary["missing_serial_numbers"],
        low_confidence_entries=validation_summary["low_confidence_entries"],
        page_level_diagnostics=diagnostics,
        parser_warnings=list(parser_input.extraction_warnings),
        requires_review=bool(invalid or unclassified),
        no_toc=False,
    )
    if not candidates:
        result.requires_review = True
        result.parser_warnings.append("No structured TOC rows could be parsed.")
    if skipped_pages:
        result.parser_warnings.append(
            f"{skipped_pages} supplied page(s) outside the effective TOC range were ignored."
        )
    return result


def _validate_range(parser_input: TocParserInput) -> None:
    start = parser_input.effective_toc_start_page
    end = parser_input.effective_toc_end_page
    if start is None or end is None:
        raise EffectiveTocRangeError("Parser requires an accepted TOC page range.")
    if start < 1 or end < start:
        raise EffectiveTocRangeError("Invalid effective TOC page range.")
    if parser_input.total_pdf_pages and end > parser_input.total_pdf_pages:
        raise EffectiveTocRangeError("Effective TOC range exceeds total PDF pages.")
