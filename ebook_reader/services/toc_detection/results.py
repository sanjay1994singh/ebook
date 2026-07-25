from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class TocBookmark:
    title: str
    target_page: int | None

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class TocDetectionResult:
    strategy_name: str
    confidence: float
    detected_start_page: int | None = None
    detected_end_page: int | None = None
    bookmarks: list[TocBookmark] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_manual_configuration: bool = False

    @property
    def found(self):
        return bool(
            self.bookmarks or self.detected_start_page or self.detected_end_page
        )

    def as_dict(self):
        data = asdict(self)
        data["found"] = self.found
        return data


def empty_result(strategy_name, warnings=None):
    return TocDetectionResult(
        strategy_name=strategy_name,
        confidence=0.0,
        warnings=warnings or [],
    )
