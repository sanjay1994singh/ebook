from collections import Counter

from .models import PageNumberSample


def score_offset(samples: list[PageNumberSample], offset: int, conflicts: list[str]) -> tuple[float, list[str]]:
    agreeing = [sample for sample in samples if sample.offset == offset]
    reasons = [f"{len(agreeing)} sample(s) agree on offset {offset}."]
    if len(agreeing) < 2:
        return 0.35, reasons + ["At least two agreeing samples are required."]

    score = 0.45
    score += min(len(agreeing), 5) * 0.08
    confidences = [
        sample.confidence
        for sample in agreeing
        if sample.confidence is not None and sample.confidence >= 0
    ]
    if confidences:
        average = sum(confidences) / len(confidences)
        normalized = average / 100 if average > 1 else average
        score += min(max(normalized, 0), 1) * 0.15
        reasons.append(f"Average sample confidence is {average:.2f}.")
    if not conflicts:
        score += 0.1
        reasons.append("No contradictory samples were found.")
    else:
        score -= min(len(conflicts) * 0.1, 0.3)
        reasons.append(f"{len(conflicts)} conflict(s) reduced confidence.")
    return round(max(min(score, 0.98), 0.0), 3), reasons


def dominant_offset(samples: list[PageNumberSample]) -> tuple[int | None, list[str]]:
    offsets = [sample.offset for sample in samples if sample.offset is not None]
    if not offsets:
        return None, ["No printed page numbers were available in samples."]
    counts = Counter(offsets)
    offset, count = counts.most_common(1)[0]
    conflicts = [
        f"Offset {other_offset} appeared in {other_count} sample(s)."
        for other_offset, other_count in counts.items()
        if other_offset != offset
    ]
    if count < 2:
        conflicts.append("Only one sample supports the dominant offset.")
    return offset, conflicts
