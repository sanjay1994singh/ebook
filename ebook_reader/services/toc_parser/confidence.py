from .models import TocCandidate, TocRow


LOW_CONFIDENCE_THRESHOLD = 0.55


def score_candidate(
    *,
    row: TocRow,
    order: int | None,
    title: str,
    printed_page_number: int | None,
    strategy_name: str,
    layout_consistent: bool,
) -> tuple[float, list[str]]:
    """Return an explainable confidence score for a parsed TOC candidate."""
    score = 0.2
    reasons = ["Base score for a parseable row."]

    if title and len(title.strip()) >= 2:
        score += 0.2
        reasons.append("Title contains readable text.")
    if order is not None:
        score += 0.15
        reasons.append("Serial/order number detected.")
    if printed_page_number is not None:
        score += 0.15
        reasons.append("Printed page number detected.")
    if layout_consistent:
        score += 0.15
        reasons.append("Row matches the page layout pattern.")

    word_confidences = [
        word.confidence for word in row.words if word.confidence is not None and word.confidence >= 0
    ]
    if word_confidences:
        average = sum(word_confidences) / len(word_confidences)
        score += min(max(average / 100, 0), 1) * 0.15
        reasons.append(f"OCR average confidence is {average:.1f}.")
    elif strategy_name == "embedded_text":
        score += 0.12
        reasons.append("Clean embedded text was used.")

    return min(round(score, 3), 0.99), reasons


def mark_low_confidence(candidate: TocCandidate) -> None:
    if candidate.confidence < LOW_CONFIDENCE_THRESHOLD:
        candidate.warnings.append("Low parser confidence; admin review is recommended.")
