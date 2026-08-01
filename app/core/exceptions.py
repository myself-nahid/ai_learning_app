"""Custom exception classes and global exception handlers for the application."""

import logging
from typing import Any, Optional

# pyrefly: ignore [missing-import]
from fastapi import Request
# pyrefly: ignore [missing-import]
from fastapi.exception_handlers import http_exception_handler
# pyrefly: ignore [missing-import]
from fastapi.responses import JSONResponse
# pyrefly: ignore [missing-import]
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppException(Exception):
    """Base application exception."""

    def __init__(self, message: str = "An unexpected error occurred", status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class NotFoundException(AppException):
    """Raised when a requested resource is not found."""

    def __init__(self, detail: str = "Resource not found"):
        super().__init__(message=detail, status_code=404)


class AuthException(AppException):
    """Raised for authentication/authorization failures."""

    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(message=detail, status_code=401)


class ForbiddenException(AppException):
    """Raised when user lacks permission."""

    def __init__(self, detail: str = "Access denied"):
        super().__init__(message=detail, status_code=403)


class ValidationException(AppException):
    """Raised for input validation errors."""

    def __init__(self, detail: str = "Validation failed"):
        super().__init__(message=detail, status_code=400)


class AIServiceException(AppException):
    """Raised when an external AI service call fails."""

    def __init__(self, detail: str = "AI service temporarily unavailable"):
        super().__init__(message=detail, status_code=503)


class ExternalAPIException(AppException):
    """Raised when an external API (NewsAPI, etc.) fails."""

    def __init__(self, detail: str = "External service temporarily unavailable"):
        super().__init__(message=detail, status_code=502)


async def global_exception_handler(request: Request, exc: Exception):
    """Global catch-all exception handler."""
    logger.error(
        "Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


async def app_exception_handler(request: Request, exc: AppException):
    """Handler for custom AppExceptions."""
    logger.warning(
        "App exception on %s %s: %s (status=%d)",
        request.method,
        request.url.path,
        exc.message,
        exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


async def http_exception_handler_wrapper(request: Request, exc: StarletteHTTPException):
    """Wrapper for Starlette HTTP exceptions to ensure logging."""
    logger.warning(
        "HTTP exception on %s %s: %s (status=%d)",
        request.method,
        request.url.path,
        exc.detail,
        exc.status_code,
    )
    return await http_exception_handler(request, exc)
