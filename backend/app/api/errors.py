"""API error handling.

The contract: a client never receives a stack trace, a ``subprocess`` repr or a
Python exception name. It receives a stable ``code`` it can branch on and a
Persian ``message`` it can display, optionally with an actionable ``hint``.

Technical detail goes to the log file, and for job failures also to the job
console, which the user opens deliberately.

Response shape::

    {
      "error": {
        "code": "ffmpeg_not_found",
        "message": "FFmpeg پیدا نشد.",
        "hint": "اسکریپت scripts/setup.ps1 را اجرا کنید...",
        "details": {...}
      }
    }
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Persian messages for the HTTP statuses the framework raises on its own.
_STATUS_MESSAGES: dict[int, str] = {
    400: "درخواست نامعتبر است.",
    404: "آدرس درخواستی پیدا نشد.",
    405: "این عملیات مجاز نیست.",
    413: "حجم درخواست بیش از حد مجاز است.",
    422: "اطلاعات ارسال‌شده معتبر نیست.",
    500: "خطای داخلی سرور رخ داد.",
}


def _payload(code: str, message: str, **extra) -> dict:
    body = {"code": code, "message": message}
    body.update({key: value for key, value in extra.items() if value})
    return {"error": body}


def register_error_handlers(app: FastAPI) -> None:
    """Attach the handlers. Called from the application factory."""

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        # Deliberate errors are already translated; log the technical side only.
        logger.info("%s: %s", exc.code, exc.message)
        return JSONResponse(status_code=exc.http_status, content={"error": exc.to_payload()})

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic's messages are English and developer-facing. Surface a
        # Persian summary and keep the field list for the UI to highlight.
        fields = [
            {
                "field": ".".join(str(part) for part in error.get("loc", [])[1:]),
                "issue": error.get("msg", ""),
            }
            for error in exc.errors()
        ]
        logger.info("request validation failed: %s", fields)
        return JSONResponse(
            status_code=422,
            content=_payload(
                "validation_error",
                "اطلاعات ارسال‌شده معتبر نیست.",
                details={"fields": fields[:10]},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        message = _STATUS_MESSAGES.get(exc.status_code)
        if message is None:
            # A handler raised HTTPException with its own Persian detail.
            message = str(exc.detail) if exc.detail else "خطایی رخ داد."
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(f"http_{exc.status_code}", message),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # The only place an untranslated exception can reach. Log everything,
        # tell the user nothing technical.
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=_payload(
                "internal_error",
                "خطای غیرمنتظره‌ای در سرور رخ داد.",
                hint="جزئیات فنی در فایل logs/app.log ثبت شده است.",
            ),
        )
