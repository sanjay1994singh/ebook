class OcrError(Exception):
    code = "ocr_error"

    def __init__(self, message, *, details=None):
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def as_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class OcrConfigurationError(OcrError):
    code = "ocr_configuration_error"


class OcrDependencyError(OcrError):
    code = "ocr_dependency_error"


class OcrTimeoutError(OcrError):
    code = "ocr_timeout"


class OcrProcessingError(OcrError):
    code = "ocr_processing_error"
