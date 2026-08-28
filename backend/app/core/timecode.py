"""Timecode parsing and formatting.

Subtitle timings are stored as **float seconds** everywhere inside the
platform. Conversion to and from the textual forms used by SRT, WebVTT and
ASS happens only at the serialisation boundary (``app/media/subtitles/``).
"""

from __future__ import annotations

import re

_TIMECODE_RE = re.compile(
    r"^(?:(?P<h>\d+):)?(?P<m>\d{1,2}):(?P<s>\d{1,2})(?:[.,](?P<ms>\d{1,3}))?$"
)


def parse_timecode(value: str) -> float:
    """Parse ``HH:MM:SS,mmm`` / ``HH:MM:SS.mmm`` / ``MM:SS`` into seconds."""
    match = _TIMECODE_RE.match(value.strip())
    if not match:
        raise ValueError(f"invalid timecode: {value!r}")
    hours = int(match.group("h") or 0)
    minutes = int(match.group("m"))
    seconds = int(match.group("s"))
    millis = int((match.group("ms") or "0").ljust(3, "0"))
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def format_srt(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS,mmm`` (SubRip)."""
    return _format(seconds, separator=",")


def format_vtt(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS.mmm`` (WebVTT)."""
    return _format(seconds, separator=".")


def format_ass(seconds: float) -> str:
    """Format seconds as ``H:MM:SS.cc`` (Advanced SubStation Alpha).

    ASS uses centiseconds and a single-digit hour field.
    """
    seconds = max(0.0, seconds)
    total_cs = int(round(seconds * 100))
    hours, rem = divmod(total_cs, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, centis = divmod(rem, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def format_clock(seconds: float) -> str:
    """Human-friendly ``HH:MM:SS`` used in the UI and logs."""
    seconds = max(0.0, seconds)
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format(seconds: float, *, separator: str) -> str:
    seconds = max(0.0, seconds)
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"
