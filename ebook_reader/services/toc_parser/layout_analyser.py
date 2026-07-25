from dataclasses import dataclass

from .models import TocRow


@dataclass(frozen=True)
class LayoutProfile:
    page_width: float
    left_boundary: float
    right_boundary: float
    has_serial_region: bool
    has_page_region: bool
    strategy_hint: str


def analyse_layout(rows: list[TocRow], page_width: float | None = None) -> LayoutProfile:
    """Infer broad column regions from row coordinates, using relative positions."""
    inferred_width = page_width or _infer_width(rows)
    if inferred_width <= 0:
        inferred_width = 1000

    left_numbers = 0
    right_numbers = 0
    for row in rows:
        if not row.words:
            continue
        first = row.words[0]
        last = row.words[-1]
        if first.left / inferred_width < 0.25 and _is_number_like(first.text):
            left_numbers += 1
        if last.right / inferred_width > 0.65 and _is_number_like(last.text):
            right_numbers += 1

    has_serial = left_numbers >= max(1, len(rows) // 4)
    has_page = right_numbers >= max(1, len(rows) // 4)
    if has_serial and has_page:
        hint = "three_column"
    elif has_serial:
        hint = "serial_title"
    elif has_page:
        hint = "two_column"
    else:
        hint = "line_pattern"

    return LayoutProfile(
        page_width=inferred_width,
        left_boundary=inferred_width * 0.22,
        right_boundary=inferred_width * 0.70,
        has_serial_region=has_serial,
        has_page_region=has_page,
        strategy_hint=hint,
    )


def _infer_width(rows: list[TocRow]) -> float:
    right = 0.0
    for row in rows:
        if row.source_box:
            right = max(right, row.source_box.right)
        for word in row.words:
            right = max(right, word.right)
    return right


def _is_number_like(text: str) -> bool:
    return any(char.isdigit() for char in text) or any(char in text for char in "०१२३४५६७८९")
