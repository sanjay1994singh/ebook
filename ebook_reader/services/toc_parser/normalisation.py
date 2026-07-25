import re
import unicodedata

from ebook_reader.services.ocr.base import normalize_devanagari_digits


TOC_HEADER_TERMS = (
    "\u0935\u093f\u0937\u092f \u0938\u0942\u091a\u0940",
    "\u0935\u093f\u0937\u092f\u0938\u0942\u091a\u0940",
    "\u0905\u0928\u0941\u0915\u094d\u0930\u092e\u0923\u093f\u0915\u093e",
    "\u092a\u093e\u0920 \u0938\u0942\u091a\u0940",
    "\u0915\u094d\u0930\u092e \u0938\u0902\u0916\u094d\u092f\u093e",
    "\u0935\u093f\u0935\u0930\u0923",
    "\u092a\u0943\u0937\u094d\u0920 \u0938\u0902\u0916\u094d\u092f\u093e",
    "contents",
    "table of contents",
)


def normalize_text(text: str) -> str:
    """Normalize spacing and Unicode without stripping meaningful Hindi marks."""
    value = unicodedata.normalize("NFC", text or "")
    value = re.sub(r"[\t\r\f\v]+", " ", value)
    value = re.sub(r" {2,}", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return value.strip()


def normalize_number_text(text: str) -> str:
    return normalize_devanagari_digits(normalize_text(text))


def parse_confident_integer(text: str, *, structural_hint: bool = False) -> int | None:
    """Parse digits, using OCR-confusion fixes only with structural evidence."""
    normalized = normalize_number_text(text)
    cleaned = re.sub(r"[^\dA-Za-z]", "", normalized)
    if cleaned.isdigit():
        return int(cleaned)
    if not structural_hint:
        return None
    confused = cleaned.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5"}))
    return int(confused) if confused.isdigit() else None


def looks_like_garbled_text(text: str) -> bool:
    value = normalize_text(text)
    if not value:
        return False
    replacement_ratio = value.count("?") / max(len(value), 1)
    mojibake_hits = sum(value.count(token) for token in ("à¤", "à¥", "Ã", "Â"))
    return replacement_ratio > 0.25 or mojibake_hits >= 3


def is_toc_heading_or_footer(text: str) -> bool:
    normalized = normalize_text(text).lower().strip(" :-|")
    if not normalized:
        return True
    if normalized in TOC_HEADER_TERMS:
        return True
    return any(term in normalized and len(normalized) <= len(term) + 8 for term in TOC_HEADER_TERMS)
