"""Errors returned by the companion service."""

from __future__ import annotations


class ServiceError(Exception):
    """An error that can be rendered as a Kroki companion JSON error response."""

    status_code = 500
    name = "Error"

    def __init__(self, message: str, *, stacktrace: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.stacktrace = stacktrace

    def to_dict(self) -> dict:
        return {"error": {"name": self.name, "message": self.message, "stacktrace": self.stacktrace}}


class BadRequest(ServiceError):
    status_code = 400
    name = "BadRequest"


class BodyTooLarge(BadRequest):
    name = "BodyTooLarge"


class MaxTextSizeError(BadRequest):
    name = "MaxTextSizeError"


class DiagramSyntaxError(BadRequest):
    name = "SyntaxError"


class ConvertTimeoutError(ServiceError):
    status_code = 408
    name = "TimeoutError"


class RenderError(ServiceError):
    status_code = 500
    name = "RenderError"


class ServiceUnavailable(ServiceError):
    status_code = 503
    name = "ServiceUnavailable"
