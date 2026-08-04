from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TocOcrWord:
    text: str
    confidence: float | None = None
    left: float = 0
    top: float = 0
    width: float = 0
    height: float = 0
    block_id: int | None = None
    paragraph_id: int | None = None
    line_id: int | None = None

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TocPageInput:
    page_number: int
    embedded_text: str = ""
    ocr_words: list[TocOcrWord] = field(default_factory=list)
    width: float | None = None
    height: float | None = None
    ocr_engine_metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TocParserInput:
    ebook_document_id: int
    effective_toc_start_page: int | None
    effective_toc_end_page: int | None
    total_pdf_pages: int | None
    pages: list[TocPageInput] = field(default_factory=list)
    extraction_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SourceBox:
    left: float
    top: float
    right: float
    bottom: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TocRow:
    source_toc_page: int
    text: str
    words: list[TocOcrWord] = field(default_factory=list)
    source_box: SourceBox | None = None
    source_line: int | None = None
    raw_source_text: str = ""
    is_header_or_footer: bool = False
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.source_box:
            data["source_box"] = self.source_box.as_dict()
        return data


@dataclass
class TocCandidate:
    order: int | None
    title: str
    printed_page_number: int | None
    proposed_pdf_page: int | None
    confidence: float
    source_toc_page: int
    source_line: int | None = None
    source_box: SourceBox | None = None
    raw_source_text: str = ""
    warnings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    parser_strategy: str = ""
    confidence_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.source_box:
            data["source_box"] = self.source_box.as_dict()
        return data


@dataclass
class PageDiagnostics:
    page_number: int
    strategy_name: str
    rows_seen: int = 0
    rows_filtered: int = 0
    warnings: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TocParsingResult:
    valid_candidates: list[TocCandidate] = field(default_factory=list)
    invalid_candidates: list[TocCandidate] = field(default_factory=list)
    unclassified_rows: list[TocRow] = field(default_factory=list)
    total_detected: int = 0
    duplicates: list[int] = field(default_factory=list)
    missing_serial_numbers: int = 0
    low_confidence_entries: int = 0
    page_level_diagnostics: list[PageDiagnostics] = field(default_factory=list)
    parser_warnings: list[str] = field(default_factory=list)
    requires_review: bool = False
    no_toc: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid_candidates": [item.as_dict() for item in self.valid_candidates],
            "invalid_candidates": [item.as_dict() for item in self.invalid_candidates],
            "unclassified_rows": [row.as_dict() for row in self.unclassified_rows],
            "total_detected": self.total_detected,
            "duplicates": self.duplicates,
            "missing_serial_numbers": self.missing_serial_numbers,
            "low_confidence_entries": self.low_confidence_entries,
            "page_level_diagnostics": [
                item.as_dict() for item in self.page_level_diagnostics
            ],
            "parser_warnings": self.parser_warnings,
            "requires_review": self.requires_review,
            "no_toc": self.no_toc,
        }
