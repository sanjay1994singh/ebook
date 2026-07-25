class TocParserError(Exception):
    """Base error for TOC parser failures."""


class EffectiveTocRangeError(TocParserError):
    """Raised when an ebook has no accepted TOC page range to parse."""
