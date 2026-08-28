"""Filesystem and process-input hardening.

The platform has no authentication (it is a single-user local application),
but the browser is still an untrusted input surface: anything reaching the API
is a string that a page could have crafted. This module is the single place
where those strings become filesystem paths.

Three distinct guarantees are provided:

1. :func:`sanitize_filename` - a user-supplied *name* becomes a safe Windows
   filename, preserving Persian/Unicode characters.
2. :func:`ensure_within` - a path is provably inside a directory the platform
   owns (blocks ``..`` traversal, absolute escapes and junction escapes).
3. :func:`validate_import_path` - a path the user picked from their own
   filesystem is a real, readable, allow-listed media file.

Command construction never goes through a shell: see ``app/process/runner.py``,
which always spawns with an argument *list* and ``shell=False``.
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path, PurePath
from typing import Iterable, Sequence

from app.core.errors import FileValidationError, PathTraversalError, SecurityError

# Characters Windows forbids in a filename, plus control characters.
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Device names Windows reserves regardless of extension.
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
# Runs of whitespace collapse to a single ASCII space.
_WHITESPACE = re.compile(r"\s+")

MAX_FILENAME_LENGTH = 120


def sanitize_filename(
    name: str,
    *,
    fallback: str = "file",
    max_length: int = MAX_FILENAME_LENGTH,
) -> str:
    """Return a filename that is safe to create on Windows.

    Unicode is preserved (Persian filenames are a first-class requirement), but
    path separators, reserved device names, control characters and trailing
    dots/spaces are removed. The result is never empty.
    """
    if not isinstance(name, str):
        raise SecurityError("filename must be a string")

    # Normalise so visually identical names collide predictably on disk.
    cleaned = unicodedata.normalize("NFC", name)
    # Take the basename only; a caller must never be able to inject a directory.
    cleaned = PurePath(cleaned.replace("\\", "/")).name
    cleaned = _ILLEGAL_CHARS.sub("_", cleaned)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    # Windows silently strips trailing dots and spaces; do it explicitly so the
    # name we record in the database matches the name on disk.
    cleaned = cleaned.rstrip(". ")

    if not cleaned:
        return fallback

    stem, dot, suffix = cleaned.rpartition(".")
    if not dot:
        stem, suffix = cleaned, ""

    if stem.lower() in _RESERVED_NAMES:
        stem = f"_{stem}"

    if suffix:
        # Keep the extension intact, trim the stem instead.
        keep = max(1, max_length - len(suffix) - 1)
        result = f"{stem[:keep]}.{suffix}"
    else:
        result = stem[:max_length]

    result = result.rstrip(". ")
    return result or fallback


def unique_path(directory: Path, filename: str) -> Path:
    """Return a non-existing path inside ``directory`` for ``filename``.

    Appends ``-1``, ``-2`` ... to the stem on collision. Never overwrites, which
    is what keeps the "never modify the original" guarantee cheap to honour.
    """
    directory.mkdir(parents=True, exist_ok=True)
    safe = sanitize_filename(filename)
    candidate = directory / safe
    if not candidate.exists():
        return candidate

    stem = Path(safe).stem
    suffix = Path(safe).suffix
    for counter in range(1, 10_000):
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
    raise SecurityError(f"could not allocate a unique filename for {filename!r}")


def ensure_within(base: Path, candidate: Path | str) -> Path:
    """Resolve ``candidate`` and assert it lives inside ``base``.

    Both sides are fully resolved first, so this also defeats symlink and
    junction escapes - relevant on Windows where directory junctions are common.
    """
    base_resolved = Path(base).resolve()
    try:
        target = Path(candidate)
        if not target.is_absolute():
            target = base_resolved / target
        target_resolved = target.resolve()
    except (OSError, ValueError) as exc:
        raise PathTraversalError(f"cannot resolve path {candidate!r}: {exc}") from exc

    if target_resolved != base_resolved and base_resolved not in target_resolved.parents:
        raise PathTraversalError(
            f"path {target_resolved} escapes base {base_resolved}",
            details={"base": str(base_resolved)},
        )
    return target_resolved


def is_within(base: Path, candidate: Path | str) -> bool:
    """Non-raising variant of :func:`ensure_within`."""
    try:
        ensure_within(base, candidate)
    except PathTraversalError:
        return False
    return True


def validate_import_path(
    raw: str,
    *,
    allowed_extensions: Sequence[str],
    allowed_roots: Iterable[Path] | None = None,
    max_bytes: int | None = None,
) -> Path:
    """Validate a path the user picked from their own Windows filesystem.

    Importing genuinely needs to read outside the workspace - the whole point
    is to pick an MP4 from anywhere on the machine - so containment is not the
    control here. Instead we require: no NUL bytes, no UNC/device prefixes, an
    existing regular file, an allow-listed extension, and an optional size cap.
    When ``allowed_roots`` is configured (Settings), the path must additionally
    sit under one of them.
    """
    if not raw or "\x00" in raw:
        raise FileValidationError("import path is empty or contains a NUL byte")

    text = raw.strip().strip('"')
    if text.startswith("\\\\"):
        raise SecurityError(
            "UNC and device paths are not accepted",
            user_message="مسیرهای شبکه‌ای پشتیبانی نمی‌شوند. لطفاً فایل را روی درایو محلی قرار دهید.",
        )

    try:
        path = Path(text).expanduser().resolve()
    except (OSError, ValueError) as exc:
        raise FileValidationError(f"cannot resolve import path: {exc}") from exc

    if not path.exists():
        raise FileValidationError(
            f"import path does not exist: {path}",
            user_message="فایل انتخاب‌شده پیدا نشد.",
        )
    if not path.is_file():
        raise FileValidationError(
            f"import path is not a regular file: {path}",
            user_message="مسیر انتخاب‌شده یک فایل نیست.",
        )

    extensions = {
        e.lower() if e.startswith(".") else f".{e.lower()}" for e in allowed_extensions
    }
    if path.suffix.lower() not in extensions:
        raise FileValidationError(
            f"extension {path.suffix!r} is not allowed",
            user_message="فرمت این فایل پشتیبانی نمی‌شود.",
            details={"allowed": sorted(extensions)},
        )

    roots = [Path(r).resolve() for r in (allowed_roots or [])]
    if roots and not any(is_within(root, path) for root in roots):
        raise PathTraversalError(
            f"{path} is outside the configured import roots",
            user_message="این مسیر خارج از پوشه‌های مجاز تعریف‌شده در تنظیمات است.",
        )

    size = path.stat().st_size
    if size == 0:
        raise FileValidationError(
            "file is empty",
            user_message="فایل انتخاب‌شده خالی است.",
        )
    if max_bytes is not None and size > max_bytes:
        raise FileValidationError(
            f"file is {size} bytes, limit is {max_bytes}",
            user_message="حجم فایل بیشتر از حد مجاز است.",
            details={"size": size, "limit": max_bytes},
        )

    if not os.access(path, os.R_OK):
        raise FileValidationError(
            f"no read permission for {path}",
            user_message="دسترسی خواندن این فایل وجود ندارد.",
        )

    return path
