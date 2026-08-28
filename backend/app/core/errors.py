"""Application error hierarchy.

Every error raised deliberately by the platform carries **two** messages:

* ``message``      - technical, English, written to logs only.
* ``user_message`` - Persian, safe to show in the UI.

The API error handler (``app/api/errors.py``) never leaks a stack trace or a
raw ``subprocess`` repr to the client; it returns the Persian message plus a
stable ``code`` the frontend can branch on. Technical detail goes to the log
file and, for job failures, to the job log which the user can open explicitly.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all deliberate application errors."""

    #: Stable machine-readable identifier, used by the frontend.
    code: str = "internal_error"
    #: HTTP status the API layer should map this to.
    http_status: int = 500
    #: Persian fallback shown when a subclass does not supply one.
    default_user_message: str = "خطای غیرمنتظره‌ای رخ داد."

    def __init__(
        self,
        message: str,
        *,
        user_message: str | None = None,
        details: dict[str, Any] | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.user_message = user_message or self.default_user_message
        self.details = details or {}
        #: Optional Persian actionable hint.
        self.hint = hint

    def to_payload(self) -> dict[str, Any]:
        """Client-safe representation. Never includes the technical message."""
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.user_message,
        }
        if self.hint:
            payload["hint"] = self.hint
        if self.details:
            payload["details"] = self.details
        return payload


# --------------------------------------------------------------------------
# Validation / lookup
# --------------------------------------------------------------------------


class ValidationError(AppError):
    code = "validation_error"
    http_status = 422
    default_user_message = "اطلاعات ارسال‌شده معتبر نیست."


class NotFoundError(AppError):
    code = "not_found"
    http_status = 404
    default_user_message = "مورد درخواستی پیدا نشد."


class ConflictError(AppError):
    code = "conflict"
    http_status = 409
    default_user_message = "این عملیات با وضعیت فعلی سازگار نیست."


# --------------------------------------------------------------------------
# Filesystem / security
# --------------------------------------------------------------------------


class SecurityError(AppError):
    code = "security_error"
    http_status = 400
    default_user_message = "این مسیر یا نام فایل مجاز نیست."


class PathTraversalError(SecurityError):
    code = "path_traversal"
    default_user_message = "مسیر انتخاب‌شده خارج از محدوده مجاز برنامه است."


class FileValidationError(AppError):
    code = "file_invalid"
    http_status = 400
    default_user_message = "فایل انتخاب‌شده معتبر نیست."


# --------------------------------------------------------------------------
# External dependencies (FFmpeg, Claude CLI, ASR engine, TTS)
# --------------------------------------------------------------------------


class DependencyError(AppError):
    """A required external tool is missing or unusable."""

    code = "dependency_missing"
    http_status = 503
    default_user_message = "یکی از ابزارهای موردنیاز در دسترس نیست."


class FFmpegNotFoundError(DependencyError):
    code = "ffmpeg_not_found"
    default_user_message = "FFmpeg پیدا نشد."

    def __init__(self, message: str = "ffmpeg executable not found", **kw: Any) -> None:
        kw.setdefault(
            "hint",
            "اسکریپت scripts/setup.ps1 را اجرا کنید یا مسیر FFmpeg را در «تنظیمات ← رسانه» وارد کنید.",
        )
        super().__init__(message, **kw)


class ClaudeCliNotFoundError(DependencyError):
    code = "claude_cli_not_found"
    default_user_message = "ابزار خط فرمان Claude پیدا نشد."

    def __init__(self, message: str = "claude executable not found", **kw: Any) -> None:
        kw.setdefault(
            "hint",
            "نصب بودن Claude CLI را بررسی کنید یا مسیر آن را در «تنظیمات ← هوش مصنوعی» وارد کنید.",
        )
        super().__init__(message, **kw)


class TranscriptionEngineNotAvailableError(DependencyError):
    code = "asr_engine_unavailable"
    default_user_message = "موتور تبدیل گفتار به متن نصب نشده است."

    def __init__(self, message: str = "asr engine unavailable", **kw: Any) -> None:
        kw.setdefault(
            "hint",
            "اسکریپت scripts/install_asr.ps1 را اجرا کنید تا موتور محلی Whisper نصب شود.",
        )
        super().__init__(message, **kw)


# --------------------------------------------------------------------------
# Process execution
# --------------------------------------------------------------------------


class ProcessError(AppError):
    """An external process exited with a non-zero status."""

    code = "process_failed"
    http_status = 500
    default_user_message = "اجرای فرآیند خارجی با خطا مواجه شد."

    def __init__(
        self,
        message: str,
        *,
        command: str = "",
        exit_code: int | None = None,
        stderr_tail: str = "",
        **kw: Any,
    ) -> None:
        details = kw.pop("details", None) or {}
        details.update({"exit_code": exit_code, "stderr_tail": stderr_tail[-2000:]})
        super().__init__(message, details=details, **kw)
        self.command = command
        self.exit_code = exit_code
        self.stderr_tail = stderr_tail


class ProcessTimeoutError(ProcessError):
    code = "process_timeout"
    default_user_message = "زمان اجرای فرآیند به پایان رسید و متوقف شد."


class ProcessCancelledError(AppError):
    code = "process_cancelled"
    http_status = 499
    default_user_message = "عملیات لغو شد."


# --------------------------------------------------------------------------
# AI layer
# --------------------------------------------------------------------------


class AIError(AppError):
    code = "ai_error"
    http_status = 502
    default_user_message = "اجرای هوش مصنوعی با خطا مواجه شد."


class ProviderNotFoundError(AIError):
    code = "provider_not_found"
    http_status = 404
    default_user_message = "ارائه‌دهنده هوش مصنوعی انتخاب‌شده در دسترس نیست."


class ModelNotFoundError(AIError):
    code = "model_not_found"
    http_status = 404
    default_user_message = "مدل انتخاب‌شده در دسترس نیست."


class TaskNotSupportedError(AIError):
    code = "task_not_supported"
    http_status = 400
    default_user_message = "این نوع پردازش توسط ارائه‌دهنده انتخاب‌شده پشتیبانی نمی‌شود."


class EmptyAIResponseError(AIError):
    code = "ai_empty_response"
    default_user_message = "پاسخی از هوش مصنوعی دریافت نشد."


# --------------------------------------------------------------------------
# Media / subtitles / TTS
# --------------------------------------------------------------------------


class MediaError(AppError):
    code = "media_error"
    http_status = 500
    default_user_message = "پردازش فایل رسانه‌ای با خطا مواجه شد."


class SubtitleError(AppError):
    code = "subtitle_error"
    http_status = 400
    default_user_message = "پردازش زیرنویس با خطا مواجه شد."


class TTSError(AppError):
    code = "tts_error"
    http_status = 502
    default_user_message = "تولید گفتار با خطا مواجه شد."


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------


class JobError(AppError):
    code = "job_error"
    http_status = 500
    default_user_message = "اجرای وظیفه با خطا مواجه شد."


class JobCancelledError(JobError):
    code = "job_cancelled"
    default_user_message = "وظیفه لغو شد."
