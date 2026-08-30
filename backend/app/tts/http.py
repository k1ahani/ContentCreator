"""Minimal HTTP client for the API-backed speech providers.

Built on :mod:`urllib.request` rather than ``requests`` or ``httpx``
deliberately. The platform's runtime dependency list is six packages
(``backend/pyproject.toml``) and every one of them earns its place; adding a
whole HTTP stack so that two optional providers can make one POST each is the
same trade the SAPI5 provider already declined when it drove PowerShell
instead of taking a ``pywin32`` dependency for one feature.

What this module is really for is the *error translation*. A provider that
lets a raw ``URLError`` escape gives the user "‹urlopen error [Errno 11001]
getaddrinfo failed›" in a Persian interface. Everything here fails as a
:class:`~app.core.errors.TTSError` carrying a Persian ``user_message`` and an
actionable ``hint``, which is the contract every other layer of this codebase
already follows (docs/DEVELOPMENT_GUIDE.md).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from app.core.errors import TTSError
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Long enough for a slow synthesis of a full paragraph, short enough that a
#: hung service does not hold a job worker forever.
DEFAULT_TIMEOUT_SECONDS = 120.0


def get_json(
    url: str, *, headers: dict[str, str], timeout: float = 30.0
) -> Any:
    """GET a JSON document. Raises :class:`TTSError` on any failure."""
    raw = _request(url, method="GET", body=None, headers=headers, timeout=timeout)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TTSError(
            f"{url} did not return valid JSON: {exc}",
            user_message="پاسخ سرویس صدا قابل خواندن نبود.",
            hint="ممکن است آدرس سرویس اشتباه باشد یا سرویس در دسترس نباشد.",
        ) from exc


def post_json_for_audio(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bytes:
    """POST JSON and read back an audio body.

    An empty body is treated as a failure here rather than being written to
    disk as a zero-byte file, so the caller never has to distinguish "the
    service answered with silence" from "the service answered with nothing".
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    audio = _request(
        url,
        method="POST",
        body=body,
        headers={"Content-Type": "application/json", **headers},
        timeout=timeout,
    )
    if not audio:
        raise TTSError(
            f"{url} returned an empty audio body",
            user_message="سرویس تولید گفتار خروجی صوتی برنگرداند.",
            hint="کمی بعد دوباره تلاش کنید یا صدای دیگری انتخاب کنید.",
        )
    return audio


def download(url: str, *, timeout: float = 30.0) -> bytes:
    """Fetch a provider-hosted file, e.g. a published voice sample."""
    return _request(url, method="GET", body=None, headers={}, timeout=timeout)


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------


def _request(
    url: str,
    *,
    method: str,
    body: bytes | None,
    headers: dict[str, str],
    timeout: float,
) -> bytes:
    if not url.lower().startswith(("http://", "https://")):
        # A mistyped base URL in settings must not become a file:// read.
        raise TTSError(
            f"refusing to request a non-HTTP url: {url!r}",
            user_message="آدرس سرویس صدا معتبر نیست.",
            hint="آدرس باید با http:// یا https:// شروع شود.",
        )

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = _read_error_body(exc)
        logger.info("%s %s failed with HTTP %s: %s", method, url, exc.code, detail[:300])
        raise TTSError(
            f"{method} {url} failed with HTTP {exc.code}: {detail[:500]}",
            user_message=_message_for_status(exc.code),
            hint=_hint_for_status(exc.code),
        ) from exc
    except urllib.error.URLError as exc:
        logger.info("%s %s could not be reached: %s", method, url, exc.reason)
        raise TTSError(
            f"{method} {url} could not be reached: {exc.reason}",
            user_message="اتصال به سرویس تولید گفتار برقرار نشد.",
            hint="اتصال اینترنت و آدرس سرویس را بررسی کنید.",
        ) from exc
    except TimeoutError as exc:
        raise TTSError(
            f"{method} {url} timed out after {timeout}s",
            user_message="سرویس تولید گفتار در زمان مقرر پاسخ نداد.",
            hint="متن کوتاه‌تری امتحان کنید یا بعداً دوباره تلاش کنید.",
        ) from exc


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    """The service's own explanation, which is usually the useful part."""
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - the body is a bonus, never required
        return ""


def _message_for_status(status: int) -> str:
    if status in (401, 403):
        return "کلید API سرویس صدا پذیرفته نشد."
    if status == 404:
        return "صدای انتخاب‌شده در این سرویس پیدا نشد."
    if status == 422:
        return "درخواست ارسالی به سرویس صدا معتبر نبود."
    if status == 429:
        return "سهمیه یا محدودیت درخواست این سرویس تمام شده است."
    if status >= 500:
        return "سرویس تولید گفتار با خطای داخلی مواجه شد."
    return "درخواست به سرویس تولید گفتار ناموفق بود."


def _hint_for_status(status: int) -> str:
    if status in (401, 403):
        return "کلید API را در «تنظیمات ← صدا» بررسی کنید."
    if status == 404:
        return "صدای دیگری از فهرست انتخاب کنید."
    if status == 429:
        return "کمی صبر کنید یا از موتور «صداهای عصبی مایکروسافت» استفاده کنید."
    if status >= 500:
        return "کمی بعد دوباره تلاش کنید."
    return "جزئیات فنی در کنسول این وظیفه ثبت شده است."
