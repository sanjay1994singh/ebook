from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PageNumberSample:
    printed_page_number: int | None
    physical_pdf_page: int
    source: str = ""
    confidence: float | None = None
    evidence: list[str] = field(default_factory=list)

    @property
    def offset(self) -> int | None:
        if self.printed_page_number is None:
            return None
        return self.physical_pdf_page - self.printed_page_number

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PageMappingAnchorPair:
    printed_page_number: int
    physical_pdf_page: int
    source: str = "manual"
    is_verified: bool = False

    @property
    def offset(self) -> int:
        return self.physical_pdf_page - self.printed_page_number

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["offset"] = self.offset
        return data


@dataclass(frozen=True)
class PageMappingResult:
    mapping_strategy: str
    proposed_offset: int | None = None
    anchor_pairs: list[PageMappingAnchorPair] = field(default_factory=list)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unmappable_candidates: list[str] = field(default_factory=list)
    status: str = "review_required"

    @property
    def usable(self) -> bool:
        return self.status in {"detected", "accepted"} and (
            self.proposed_offset is not None or bool(self.anchor_pairs)
        )

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["usable"] = self.usable
        data["anchor_pairs"] = [anchor.as_dict() for anchor in self.anchor_pairs]
        return data
