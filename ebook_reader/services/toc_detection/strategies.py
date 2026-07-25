from pypdf.errors import PyPdfError

from .results import TocBookmark, TocDetectionResult, empty_result


class PdfBookmarkStrategy:
    name = "pdf_bookmarks"

    def detect(self, reader, ebook_document, *, max_pages=40):
        bookmarks = []

        def walk(items):
            for item in items:
                if isinstance(item, list):
                    walk(item)
                    continue

                title = (getattr(item, "title", "") or "").strip()
                if not title:
                    continue

                target_page = None
                try:
                    target_page = reader.get_destination_page_number(item) + 1
                except Exception:
                    pass
                bookmarks.append(TocBookmark(title=title, target_page=target_page))

        try:
            walk(reader.outline)
        except PyPdfError:
            return empty_result(
                self.name,
                warnings=["PDF outlines/bookmarks could not be read."],
            )

        if not bookmarks:
            return empty_result(self.name)

        return TocDetectionResult(
            strategy_name=self.name,
            confidence=0.7,
            bookmarks=bookmarks,
            evidence=[f"{len(bookmarks)} PDF bookmark(s) found."],
            warnings=["Bookmarks identify chapters, not the printed TOC page range."],
            requires_manual_configuration=True,
        )


class EmbeddedTextTocStrategy:
    name = "embedded_text_toc"
    toc_indicators = (
        "\u0935\u093f\u0937\u092f \u0938\u0942\u091a\u0940",
        "\u0935\u093f\u0937\u092f\u0938\u0942\u091a\u0940",
        "\u0905\u0928\u0941\u0915\u094d\u0930\u092e\u0923\u093f\u0915\u093e",
        "\u092a\u093e\u0920 \u0938\u0942\u091a\u0940",
        "\u0915\u094d\u0930\u092e \u0938\u0902\u0916\u094d\u092f\u093e",
        "\u0935\u093f\u0935\u0930\u0923",
        "\u092a\u0943\u0937\u094d\u0920 \u0938\u0902\u0916\u094d\u092f\u093e",
        "table of contents",
        "contents",
    )
    column_headers = (
        "\u0915\u094d\u0930\u092e \u0938\u0902\u0916\u094d\u092f\u093e",
        "\u0935\u093f\u0935\u0930\u0923",
        "\u092a\u0943\u0937\u094d\u0920 \u0938\u0902\u0916\u094d\u092f\u093e",
    )

    def detect(self, reader, ebook_document, *, max_pages=40):
        return self.detect_from_text_pages(_extract_text_pages(reader, max_pages))

    def detect_from_text_pages(self, page_texts):
        scan_limit = len(page_texts)
        matches = self._find_matches(page_texts)
        if not matches:
            return empty_result(
                self.name,
                warnings=[f"No TOC indicators found in first {scan_limit} page(s)."],
            )
        return self._result_from_matches(matches)

    def _find_matches(self, page_texts):
        matches = []
        for page_number, page_text in page_texts:
            normalized_text = (page_text or "").lower()
            matched_indicators = [
                value
                for value in self.toc_indicators
                if value.lower() in normalized_text
            ]
            matched_headers = [
                value
                for value in self.column_headers
                if value.lower() in normalized_text
            ]
            numeric_row_count = self._numeric_row_count(page_text)
            if (
                matched_indicators
                or len(matched_headers) >= 2
                or numeric_row_count >= 3
            ):
                matches.append(
                    {
                        "page": page_number,
                        "indicators": matched_indicators,
                        "headers": matched_headers,
                        "numeric_row_count": numeric_row_count,
                    }
                )
        return matches

    def _result_from_matches(self, matches):
        start_page = matches[0]["page"]
        end_page = start_page
        for match in matches[1:]:
            if match["page"] == end_page + 1:
                end_page = match["page"]
                continue
            break

        evidence = [
            (
                f"Page {match['page']} matched indicators={match['indicators']} "
                f"headers={match['headers']} numeric_rows={match['numeric_row_count']}"
            )
            for match in matches
        ]
        return TocDetectionResult(
            strategy_name=self.name,
            confidence=self._confidence(matches),
            detected_start_page=start_page,
            detected_end_page=end_page,
            evidence=evidence,
        )

    def _numeric_row_count(self, text):
        count = 0
        for line in (text or "").splitlines():
            tokens = line.split()
            if len(tokens) >= 3 and tokens[0].strip(".").isdigit() and tokens[-1].isdigit():
                count += 1
        return count

    def _confidence(self, matches):
        first_match = matches[0]
        if first_match["indicators"] and first_match["headers"]:
            return 0.95
        if first_match["indicators"] and first_match["numeric_row_count"] >= 3:
            return 0.9
        if len(matches) > 1 and first_match["indicators"]:
            return 0.88
        if first_match["indicators"]:
            return 0.78
        if first_match["numeric_row_count"] >= 3:
            return 0.65
        return 0.55


class OcrTocStrategy(EmbeddedTextTocStrategy):
    name = "ocr_toc"

    def __init__(self, ocr_text_provider=None):
        self.ocr_text_provider = ocr_text_provider

    def detect(self, reader, ebook_document, *, max_pages=40):
        if self.ocr_text_provider is None:
            return empty_result(
                self.name,
                warnings=["OCR provider is not configured; OCR fallback was skipped."],
            )

        total_pages = len(reader.pages)
        scan_limit = min(max_pages, total_pages)
        page_texts = []
        warnings = []
        for page_index in range(scan_limit):
            page_number = page_index + 1
            try:
                page_text = self.ocr_text_provider(reader, page_index) or ""
            except Exception as error:
                warnings.append(f"Page {page_number} OCR failed: {error}")
                page_text = ""
            page_texts.append((page_number, page_text))

        matches = self._find_matches(page_texts)
        if not matches:
            return empty_result(
                self.name,
                warnings=warnings
                + [f"No TOC indicators found in first {scan_limit} page(s)."],
            )

        result = self._result_from_matches(matches)
        return TocDetectionResult(
            strategy_name=self.name,
            confidence=result.confidence,
            detected_start_page=result.detected_start_page,
            detected_end_page=result.detected_end_page,
            evidence=result.evidence + ["OCR fallback supplied usable text."],
            warnings=warnings,
        )


def _extract_text_pages(reader, max_pages):
    total_pages = len(reader.pages)
    scan_limit = min(max_pages, total_pages)
    page_texts = []
    for page_index in range(scan_limit):
        page_number = page_index + 1
        try:
            page_text = reader.pages[page_index].extract_text() or ""
        except PyPdfError:
            page_text = ""
        page_texts.append((page_number, page_text if _is_usable_text(page_text) else ""))
    return page_texts


def _is_usable_text(text):
    stripped = (text or "").strip()
    if not stripped:
        return False
    question_ratio = stripped.count("?") / max(len(stripped), 1)
    return question_ratio < 0.35
