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
        return LinePatternStrategy(strategy_name=self.name).parse_page(page, rows)


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
    if not title:
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

    if not title:
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
