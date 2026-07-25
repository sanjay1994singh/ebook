import re
from typing import Protocol

from .confidence import score_candidate
from .layout_analyser import LayoutProfile, analyse_layout
from .models import TocCandidate, TocPageInput, TocRow
from .normalisation import (
    looks_like_garbled_text,
    normalize_number_text,
    normalize_text,
    parse_confident_integer,
)


class ParserStrategy(Protocol):
    name: str

    def parse_page(self, page: TocPageInput, rows: list[TocRow]) -> tuple[list[TocCandidate], list[TocRow]]:
        raise NotImplementedError


class EmbeddedTextStrategy:
    name = "embedded_text"

    def parse_page(self, page: TocPageInput, rows: list[TocRow]) -> tuple[list[TocCandidate], list[TocRow]]:
        if not page.embedded_text or looks_like_garbled_text(page.embedded_text):
            return [], rows
        block_candidates, block_unclassified = EmbeddedColumnBlockStrategy().parse_page(page, rows)
        if block_candidates:
            return block_candidates, block_unclassified
        return LinePatternStrategy(strategy_name=self.name).parse_page(page, rows)


class EmbeddedColumnBlockStrategy:
    name = "embedded_column_block"

    def parse_page(self, page: TocPageInput, rows: list[TocRow]) -> tuple[list[TocCandidate], list[TocRow]]:
        serial_rows: list[TocRow] = []
        printed_page_rows: list[TocRow] = []
        title_rows: list[TocRow] = []
        unclassified: list[TocRow] = []

        for row in rows:
            text = normalize_text(row.text)
            if not text or _looks_like_embedded_header_or_footer(text):
                unclassified.append(row)
                continue
            if _is_physical_page_marker(text, page.page_number):
                unclassified.append(row)
                continue
            if _serial_number_line(text) is not None:
                serial_rows.append(row)
                continue
            if _standalone_number_line(text) is not None:
                printed_page_rows.append(row)
                continue
            title = _clean_title(text)
            if _is_meaningful_title(title):
                title_rows.append(row)
            else:
                unclassified.append(row)

        entry_count = min(len(serial_rows), len(printed_page_rows), len(title_rows))
        if entry_count < 2:
            return [], rows

        candidates = []
        for index in range(entry_count):
            serial_row = serial_rows[index]
            title_row = title_rows[index]
            page_row = printed_page_rows[index]
            order = _serial_number_line(serial_row.text)
            page_number = _standalone_number_line(page_row.text)
            title = _clean_title(title_row.text)
            confidence, reasons = score_candidate(
                row=title_row,
                order=order,
                title=title,
                printed_page_number=page_number,
                strategy_name=self.name,
                layout_consistent=True,
            )
            candidates.append(
                TocCandidate(
                    order=order,
                    title=title,
                    printed_page_number=page_number,
                    proposed_pdf_page=None,
                    confidence=confidence,
                    source_toc_page=title_row.source_toc_page,
                    source_line=title_row.source_line,
                    source_box=title_row.source_box,
                    raw_source_text="\n".join(
                        [
                            serial_row.raw_source_text or serial_row.text,
                            title_row.raw_source_text or title_row.text,
                            page_row.raw_source_text or page_row.text,
                        ]
                    ),
                    warnings=list(title_row.warnings),
                    parser_strategy=self.name,
                    confidence_reasons=reasons
                    + ["Serial, title and printed-page text blocks were paired by order."],
                )
            )

        leftovers = (
            serial_rows[entry_count:]
            + printed_page_rows[entry_count:]
            + title_rows[entry_count:]
            + unclassified
        )
        for row in leftovers:
            row.warnings.append("Embedded text block parser could not safely pair this row.")
        return candidates, leftovers


class ThreeColumnAnchorStrategy:
    name = "three_column_anchor"

    def parse_page(self, page: TocPageInput, rows: list[TocRow]) -> tuple[list[TocCandidate], list[TocRow]]:
        profile = analyse_layout(rows, page.width)
        if profile.strategy_hint not in ("three_column", "serial_title"):
            return [], rows

        candidates = []
        unclassified = []
        for row in rows:
            candidate = _candidate_from_columns(
                row,
                profile,
                strategy_name=self.name,
                require_order=True,
                layout_consistent=True,
            )
            if candidate:
                candidates.append(candidate)
            else:
                unclassified.append(row)
        return candidates, unclassified


class TwoColumnTitlePageStrategy:
    name = "two_column_title_page"

    def parse_page(self, page: TocPageInput, rows: list[TocRow]) -> tuple[list[TocCandidate], list[TocRow]]:
        profile = analyse_layout(rows, page.width)
        if not profile.has_page_region:
            return [], rows

        candidates = []
        unclassified = []
        for row in rows:
            candidate = _candidate_from_columns(
                row,
                profile,
                strategy_name=self.name,
                require_order=False,
                layout_consistent=profile.strategy_hint == "two_column",
            )
            if candidate and candidate.printed_page_number is not None:
                candidates.append(candidate)
            else:
                unclassified.append(row)
        return candidates, unclassified


class LinePatternStrategy:
    name = "line_pattern"

    def __init__(self, *, strategy_name: str | None = None):
        self.name = strategy_name or self.name

    def parse_page(self, page: TocPageInput, rows: list[TocRow]) -> tuple[list[TocCandidate], list[TocRow]]:
        candidates = []
        unclassified = []
        for row in rows:
            candidate = _candidate_from_line(row, self.name)
            if candidate:
                candidates.append(candidate)
            else:
                unclassified.append(row)
        return candidates, unclassified


class TitleOnlyOcrStrategy:
    name = "title_only_ocr"

    def parse_page(self, page: TocPageInput, rows: list[TocRow]) -> tuple[list[TocCandidate], list[TocRow]]:
        candidates = []
        unclassified = []
        source_line = 0
        page_is_devanagari_dominant = _page_is_devanagari_dominant(rows)
        for row in rows:
            raw_lines = (row.raw_source_text or row.text).splitlines() or [row.text]
            row_created = False
            for raw_line in raw_lines:
                source_line += 1
                title = _clean_title(raw_line)
                if page_is_devanagari_dominant:
                    title = _clean_devanagari_ocr_title(title)
                if not _is_reviewable_title_only_line(
                    title,
                    page_is_devanagari_dominant=page_is_devanagari_dominant,
                ):
                    continue
                confidence, reasons = score_candidate(
                    row=row,
                    order=None,
                    title=title,
                    printed_page_number=None,
                    strategy_name=self.name,
                    layout_consistent=False,
                )
                warnings = list(row.warnings)
                warnings.append("Serial and printed page number were not available; title was kept for admin review.")
                candidates.append(
                    TocCandidate(
                        order=None,
                        title=title,
                        printed_page_number=None,
                        proposed_pdf_page=None,
                        confidence=confidence,
                        source_toc_page=row.source_toc_page,
                        source_line=row.source_line or source_line,
                        source_box=row.source_box,
                        raw_source_text=raw_line,
                        warnings=warnings,
                        parser_strategy=self.name,
                        confidence_reasons=reasons
                        + ["OCR produced reviewable title text without reliable numeric anchors."],
                    )
                )
                row_created = True
            if not row_created:
                row.warnings.append("OCR row did not contain a reviewable title.")
                unclassified.append(row)
        return candidates, unclassified


class ReviewOnlyFallbackStrategy:
    name = "review_only_fallback"

    def parse_page(self, page: TocPageInput, rows: list[TocRow]) -> tuple[list[TocCandidate], list[TocRow]]:
        for row in rows:
            row.warnings.append("No reliable parser strategy matched this row.")
        return [], rows


def choose_strategy(page: TocPageInput, rows: list[TocRow]) -> ParserStrategy:
    if page.embedded_text and not looks_like_garbled_text(page.embedded_text):
        return EmbeddedTextStrategy()
    profile = analyse_layout(rows, page.width)
    if profile.strategy_hint in ("three_column", "serial_title"):
        return ThreeColumnAnchorStrategy()
    if profile.strategy_hint == "two_column":
        return TwoColumnTitlePageStrategy()
    return LinePatternStrategy()


def _is_meaningful_title(text: str) -> bool:
    value = normalize_text(text).strip()
    if not value:
        return False
    if parse_confident_integer(value, structural_hint=True) is not None:
        return False
    return any(char.isalpha() for char in value)


def _is_reviewable_title_only_line(text: str, *, page_is_devanagari_dominant: bool = False) -> bool:
    value = normalize_text(text).strip()
    if _is_devanagari_footer_or_note(value):
        return False
    if not _is_meaningful_title(value):
        return False
    if len(value) < 4:
        return False
    letters = sum(char.isalpha() for char in value)
    digits = sum(char.isdigit() for char in normalize_number_text(value))
    devanagari_letters = sum("\u0900" <= char <= "\u097f" for char in value)
    ascii_letters = sum(char.isascii() and char.isalpha() for char in value)
    if digits and digits >= letters:
        return False
    if value.startswith("(") and digits:
        return False
    if page_is_devanagari_dominant and devanagari_letters == 0 and ascii_letters >= 6:
        return False
    return True


def _is_devanagari_footer_or_note(text: str) -> bool:
    value = normalize_text(text)
    footer_phrases = (
        "द्वारा",
        "केलिमाल जी की",
        "वस्तु दर्शनी",
        "भाव वर्णन टीका",
        "महाराज जी द्वारा",
    )
    if any(phrase in value for phrase in footer_phrases):
        return True
    if value.startswith("(") and "से" in value and "तक" in value:
        return True
    return False


def _clean_devanagari_ocr_title(text: str) -> str:
    value = normalize_text(text)
    if not value:
        return ""
    if not any("\u0900" <= char <= "\u097f" for char in value):
        return value
    words = []
    for token in value.split():
        cleaned_token = token.strip(".,;:!?()[]{}\"'")
        corrected_token = _common_devanagari_ocr_correction(cleaned_token)
        if corrected_token:
            words.append(token.replace(cleaned_token, corrected_token))
            continue
        if cleaned_token.isascii() and any(char.isalpha() for char in cleaned_token):
            continue
        words.append(token)
    return normalize_text(" ".join(words))


def _common_devanagari_ocr_correction(token: str) -> str:
    corrections = {
        "ms": "माई",
        "mai": "माई",
        "maai": "माई",
        "wt": "जू",
    }
    return corrections.get(token.lower(), "")


def _page_is_devanagari_dominant(rows: list[TocRow]) -> bool:
    text = "\n".join(row.raw_source_text or row.text for row in rows)
    devanagari_letters = sum("\u0900" <= char <= "\u097f" for char in text)
    ascii_letters = sum(char.isascii() and char.isalpha() for char in text)
    return devanagari_letters >= 20 and devanagari_letters >= ascii_letters


def _standalone_number_line(text: str) -> int | None:
    value = normalize_text(text).strip()
    if value and all(char.isdigit() for char in value):
        return parse_confident_integer(value, structural_hint=True)
    return None


def _serial_number_line(text: str) -> int | None:
    value = normalize_text(text).strip()
    number_text = value.rstrip("-.) :")
    if number_text != value and number_text and all(char.isdigit() for char in number_text):
        return parse_confident_integer(number_text, structural_hint=True)
    return None


def _is_physical_page_marker(text: str, page_number: int) -> bool:
    return _standalone_number_line(text) == page_number


def _looks_like_embedded_header_or_footer(text: str) -> bool:
    value = normalize_text(text).lower()
    header_tokens = [
        "contents",
        "table of contents",
        "fo'k",
        "lwph",
        "fooj.k",
        "dz0",
        "la0",
        "i`0",
    ]
    return any(token in value for token in header_tokens)


def _candidate_from_columns(
    row: TocRow,
    profile: LayoutProfile,
    *,
    strategy_name: str,
    require_order: bool,
    layout_consistent: bool,
) -> TocCandidate | None:
    if not row.words:
        return _candidate_from_line(row, strategy_name)

    ordered_words = list(row.words)
    serial_words = []
    if ordered_words and parse_confident_integer(ordered_words[0].text, structural_hint=True) is not None:
        serial_words = [ordered_words[0]]
    else:
        serial_words = [
            word
            for word in ordered_words
            if word.right <= profile.left_boundary
            and parse_confident_integer(word.text, structural_hint=True) is not None
        ][:1]
    right_words = [word for word in ordered_words if word.left >= profile.right_boundary]
    if not right_words and ordered_words:
        trailing_number = parse_confident_integer(ordered_words[-1].text, structural_hint=True)
        if trailing_number is not None and ordered_words[-1] not in serial_words:
            right_words = [ordered_words[-1]]
    middle_words = [
        word
        for word in ordered_words
        if word not in serial_words and word not in right_words
    ]

    order = parse_confident_integer(" ".join(word.text for word in serial_words), structural_hint=True)
    page_number = parse_confident_integer(" ".join(word.text for word in right_words), structural_hint=True)
    if require_order and order is None:
        return None
    if page_number is None:
        page_number = _trailing_number(row.text)
    title = normalize_text(" ".join(word.text for word in middle_words))
    if not title and not require_order:
        without_page = _remove_trailing_number(row.text)
        title = normalize_text(without_page)
    title = _clean_title(title)
    if not _is_meaningful_title(title):
        return None

    confidence, reasons = score_candidate(
        row=row,
        order=order,
        title=title,
        printed_page_number=page_number,
        strategy_name=strategy_name,
        layout_consistent=layout_consistent,
    )
    warnings = list(row.warnings)
    if order is None:
        warnings.append("Serial/order number was not available.")
    if page_number is None:
        warnings.append("Printed page number was not available.")
    return TocCandidate(
        order=order,
        title=title,
        printed_page_number=page_number,
        proposed_pdf_page=None,
        confidence=confidence,
        source_toc_page=row.source_toc_page,
        source_line=row.source_line,
        source_box=row.source_box,
        raw_source_text=row.raw_source_text or row.text,
        warnings=warnings,
        parser_strategy=strategy_name,
        confidence_reasons=reasons,
    )


def _candidate_from_line(row: TocRow, strategy_name: str) -> TocCandidate | None:
    text = normalize_text(row.text)
    if not text:
        return None
    match = re.match(r"^\s*([0-9०-९]+)[\.\)।:\-\s]+(.+?)\s+([0-9०-९]+)\s*$", text)
    if match:
        order = parse_confident_integer(match.group(1))
        title = _clean_title(match.group(2))
        page_number = parse_confident_integer(match.group(3))
    else:
        page_number = _trailing_number(text)
        if page_number is None:
            return None
        order = None
        title = _clean_title(_remove_trailing_number(text))

    if not _is_meaningful_title(title):
        return None
    confidence, reasons = score_candidate(
        row=row,
        order=order,
        title=title,
        printed_page_number=page_number,
        strategy_name=strategy_name,
        layout_consistent=True,
    )
    warnings = list(row.warnings)
    if order is None:
        warnings.append("Serial/order number was not available.")
    return TocCandidate(
        order=order,
        title=title,
        printed_page_number=page_number,
        proposed_pdf_page=None,
        confidence=confidence,
        source_toc_page=row.source_toc_page,
        source_line=row.source_line,
        source_box=row.source_box,
        raw_source_text=row.raw_source_text or row.text,
        warnings=warnings,
        parser_strategy=strategy_name,
        confidence_reasons=reasons,
    )


def _trailing_number(text: str) -> int | None:
    match = re.search(r"([0-9०-९]+)\s*$", normalize_number_text(text))
    return parse_confident_integer(match.group(1)) if match else None


def _remove_trailing_number(text: str) -> str:
    return re.sub(r"\s+[0-9०-९]+\s*$", "", text).strip()


def _clean_title(text: str) -> str:
    value = normalize_text(text)
    value = re.sub(r"^[0-9०-९]+[\.\)।:\-\s]+", "", value)
    value = re.sub(r"\s+[0-9०-९]+$", "", value)
    return value.strip(" .।:-")
