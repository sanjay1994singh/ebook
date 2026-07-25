from django.conf import settings

from ebook_reader.services.pdf_metadata import EbookPdfError, open_pdf_reader

from .results import TocDetectionResult
from .strategies import EmbeddedTextTocStrategy, OcrTocStrategy, PdfBookmarkStrategy


def detect_ebook_toc(
    ebook_document,
    *,
    max_pages=None,
    strategies=None,
    ocr_text_provider=None,
):
    scan_limit = _scan_limit(ebook_document, max_pages)

    if ebook_document.toc_mode == ebook_document.TocMode.NONE:
        return _with_attempts(
            TocDetectionResult(
                strategy_name="none",
                confidence=1.0,
                evidence=["EbookDocument is configured as no TOC."],
            ),
            [],
            0,
        )

    if ebook_document.toc_mode == ebook_document.TocMode.MANUAL:
        return _with_attempts(
            TocDetectionResult(
                strategy_name="manual_range",
                confidence=1.0,
                detected_start_page=ebook_document.toc_start_page,
                detected_end_page=ebook_document.toc_end_page,
                evidence=["Manual TOC page range is configured on EbookDocument."],
            ),
            [],
            0,
        )

    _pdf_file, reader = open_pdf_reader(ebook_document)
    if reader.is_encrypted:
        raise EbookPdfError(
            "encrypted_pdf",
            "PDF is encrypted and cannot be inspected without a password.",
            ebook_id=ebook_document.id,
            book_id=ebook_document.book_id,
        )

    attempted_results = []
    active_strategies = strategies or (
        EmbeddedTextTocStrategy(),
        OcrTocStrategy(ocr_text_provider=ocr_text_provider),
        PdfBookmarkStrategy(),
    )

    for strategy in active_strategies:
        result = strategy.detect(reader, ebook_document, max_pages=scan_limit)
        attempted_results.append(result)
        if result.found and result.detected_start_page and result.detected_end_page:
            return _with_attempts(result, attempted_results, scan_limit)

    return _with_attempts(
        TocDetectionResult(
            strategy_name="none",
            confidence=0.0,
            requires_manual_configuration=True,
            warnings=["No TOC location detected; manual configuration is required."],
        ),
        attempted_results,
        scan_limit,
    )


def _scan_limit(ebook_document, max_pages):
    return (
        max_pages
        or ebook_document.toc_scan_page_limit
        or getattr(settings, "EBOOK_READER_TOC_SCAN_PAGE_LIMIT", 40)
    )


def _with_attempts(result, attempted_results, scan_limit):
    attempts = [
        {
            "strategy_name": item.strategy_name,
            "confidence": item.confidence,
            "found": item.found,
        }
        for item in attempted_results
    ]
    return {
        **result.as_dict(),
        "scan_limit_pages": scan_limit,
        "attempted_strategies": attempts,
    }
