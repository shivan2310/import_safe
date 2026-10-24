class ImportSafeError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidUrlError(ImportSafeError):
    status_code = 422
    code = "invalid_url"


class TinyFishNotConfiguredError(ImportSafeError):
    status_code = 503
    code = "tinyfish_not_configured"


class TinyFishFailureError(ImportSafeError):
    status_code = 502
    code = "tinyfish_failure"


class PageUnavailableError(ImportSafeError):
    status_code = 422
    code = "page_unavailable"


class IncompleteExtractionError(ImportSafeError):
    status_code = 422
    code = "incomplete_extraction"
