class PageMappingError(Exception):
    """Base error for printed-page mapping failures."""


class PageMappingValidationError(PageMappingError):
    """Raised when a proposed printed/physical page mapping is invalid."""
