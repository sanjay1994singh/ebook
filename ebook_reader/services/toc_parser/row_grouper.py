from collections import Counter, defaultdict

from .models import SourceBox, TocOcrWord, TocPageInput, TocRow
from .normalisation import is_toc_heading_or_footer, normalize_text


def rows_from_page(page: TocPageInput) -> list[TocRow]:
    if page.ocr_words:
        return _rows_from_words(page)
    return _rows_from_embedded_text(page)


def filter_repeated_headers_and_footers(page_rows: dict[int, list[TocRow]]) -> dict[int, list[TocRow]]:
    repeated = Counter()
    for rows in page_rows.values():
        seen_on_page = {normalize_text(row.text).lower() for row in rows[:2] + rows[-2:]}
        repeated.update(value for value in seen_on_page if value)

    repeated_texts = {text for text, count in repeated.items() if count > 1}
    filtered = {}
    for page_number, rows in page_rows.items():
        filtered_rows = []
        for row in rows:
            normalized = normalize_text(row.text).lower()
            if normalized in repeated_texts or is_toc_heading_or_footer(row.text):
                row.is_header_or_footer = True
            else:
                filtered_rows.append(row)
        filtered[page_number] = filtered_rows
    return filtered


def _rows_from_words(page: TocPageInput) -> list[TocRow]:
    grouped: dict[tuple[int | None, int | None, int | None], list[TocOcrWord]] = defaultdict(list)
    loose_rows: list[list[TocOcrWord]] = []

    for word in sorted(page.ocr_words, key=lambda item: (item.top, item.left)):
        key = (word.block_id, word.paragraph_id, word.line_id)
        if word.line_id is not None:
            grouped[key].append(word)
            continue
        _append_loose_word(loose_rows, word)

    word_lines = list(grouped.values()) + loose_rows
    rows = []
    for line_index, words in enumerate(
        sorted(word_lines, key=lambda items: (min(word.top for word in items), min(word.left for word in items))),
        start=1,
    ):
        ordered = sorted(words, key=lambda item: item.left)
        text = normalize_text(" ".join(word.text for word in ordered))
        if not text:
            continue
        rows.append(
            TocRow(
                source_toc_page=page.page_number,
                text=text,
                words=ordered,
                source_box=_box_for_words(ordered),
                source_line=line_index,
                raw_source_text=text,
            )
        )
    return _join_wrapped_rows(rows)


def _rows_from_embedded_text(page: TocPageInput) -> list[TocRow]:
    rows = []
    for line_index, line in enumerate(normalize_text(page.embedded_text).splitlines(), start=1):
        text = normalize_text(line)
        if text:
            rows.append(
                TocRow(
                    source_toc_page=page.page_number,
                    text=text,
                    source_line=line_index,
                    raw_source_text=text,
                )
            )
    return rows


def _append_loose_word(rows: list[list[TocOcrWord]], word: TocOcrWord) -> None:
    for row in rows:
        row_top = min(item.top for item in row)
        row_bottom = max(item.bottom for item in row)
        overlap = min(row_bottom, word.bottom) - max(row_top, word.top)
        if overlap >= min(word.height, row_bottom - row_top) * 0.45:
            row.append(word)
            return
    rows.append([word])


def _join_wrapped_rows(rows: list[TocRow]) -> list[TocRow]:
    joined: list[TocRow] = []
    for row in rows:
        if (
            joined
            and _looks_like_title_continuation(row)
            and not _looks_like_new_entry(row)
            and not (_ends_with_number(joined[-1]) and _ends_with_number(row))
            and _vertical_gap(joined[-1], row) < max(_row_height(joined[-1]) * 1.8, 24)
        ):
            previous = joined[-1]
            previous.text = normalize_text(f"{previous.text} {row.text}")
            previous.raw_source_text = normalize_text(f"{previous.raw_source_text}\n{row.raw_source_text}")
            previous.words.extend(row.words)
            previous.source_box = _merge_boxes(previous.source_box, row.source_box)
            previous.warnings.append("Wrapped title line joined by layout evidence.")
            continue
        joined.append(row)
    return joined


def _looks_like_title_continuation(row: TocRow) -> bool:
    if not row.words:
        return False
    return row.words[0].left > 40


def _looks_like_new_entry(row: TocRow) -> bool:
    first_token = row.text.split(maxsplit=1)[0].strip(".।:-")
    return any(char.isdigit() for char in first_token) or any(char in first_token for char in "०१२३४५६७८९")


def _ends_with_number(row: TocRow) -> bool:
    last_token = row.text.split()[-1].strip(".।:-") if row.text.split() else ""
    return any(char.isdigit() for char in last_token) or any(char in last_token for char in "०१२३४५६७८९")


def _vertical_gap(previous: TocRow, row: TocRow) -> float:
    if not previous.source_box or not row.source_box:
        return 999
    return row.source_box.top - previous.source_box.bottom


def _row_height(row: TocRow) -> float:
    if not row.source_box:
        return 12
    return max(row.source_box.bottom - row.source_box.top, 1)


def _box_for_words(words: list[TocOcrWord]) -> SourceBox:
    return SourceBox(
        left=min(word.left for word in words),
        top=min(word.top for word in words),
        right=max(word.right for word in words),
        bottom=max(word.bottom for word in words),
    )


def _merge_boxes(first: SourceBox | None, second: SourceBox | None) -> SourceBox | None:
    if not first:
        return second
    if not second:
        return first
    return SourceBox(
        left=min(first.left, second.left),
        top=min(first.top, second.top),
        right=max(first.right, second.right),
        bottom=max(first.bottom, second.bottom),
    )
