"""Subtitle serialisation and parsing.

Supports SRT, WebVTT and ASS. Cues live in memory as
:class:`~app.domain.subtitle.SubtitleCue` with float-second timings; this module
is the only place those become text.

ASS is what the renderer actually burns in, because it is the only one of the
three that carries styling FFmpeg can honour. SRT and VTT exist for export.

Persian-specific care:

* Text is written as UTF-8 **without** a BOM for ASS (libass mis-handles a BOM
  in some builds) and **with** one for SRT, where players commonly guess the
  encoding wrongly without it.
* Line breaks inside a cue become ``\\N`` in ASS, a hard line break, rather than
  ``\\n``, which ASS treats as collapsible.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Sequence

from app.core.errors import SubtitleError
from app.core.timecode import format_ass, format_srt, format_vtt, parse_timecode
from app.domain.subtitle import SubtitleCue, SubtitleStyle
from app.media.subtitles.style import to_ass_style_line

#: Default canvas the ASS script is authored against. FFmpeg scales the result
#: to the real video size, so font sizes stay predictable across resolutions.
ASS_PLAY_RES_X = 1920
ASS_PLAY_RES_Y = 1080


# --------------------------------------------------------------------------
# SubRip (.srt)
# --------------------------------------------------------------------------


def to_srt(cues: Sequence[SubtitleCue]) -> str:
    blocks: list[str] = []
    for number, cue in enumerate(_sorted(cues), start=1):
        blocks.append(
            f"{number}\n"
            f"{format_srt(cue.start)} --> {format_srt(cue.end)}\n"
            f"{cue.text.strip()}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


_SRT_BLOCK_RE = re.compile(
    r"(?P<index>\d+)\s*\n"
    r"(?P<start>[\d:,.]+)\s*-->\s*(?P<end>[\d:,.]+)[^\n]*\n"
    r"(?P<text>(?:.+\n?)*?)(?=\n\s*\n|\n*\Z)",
    re.MULTILINE,
)


def parse_srt(content: str) -> list[tuple[float, float, str]]:
    """Parse SRT into ``(start, end, text)`` tuples."""
    text = content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    results: list[tuple[float, float, str]] = []
    for match in _SRT_BLOCK_RE.finditer(text):
        try:
            start = parse_timecode(match.group("start"))
            end = parse_timecode(match.group("end"))
        except ValueError as exc:
            raise SubtitleError(
                f"invalid timecode in SRT block {match.group('index')}: {exc}",
                user_message="فایل زیرنویس زمان‌بندی نامعتبر دارد.",
            ) from exc
        body = match.group("text").strip()
        if end > start and body:
            results.append((start, end, body))
    if not results:
        raise SubtitleError(
            "no usable cues found in SRT content",
            user_message="هیچ زیرنویس معتبری در این فایل پیدا نشد.",
        )
    return results


# --------------------------------------------------------------------------
# WebVTT (.vtt)
# --------------------------------------------------------------------------


def to_vtt(cues: Sequence[SubtitleCue]) -> str:
    lines = ["WEBVTT", ""]
    for number, cue in enumerate(_sorted(cues), start=1):
        lines.append(str(number))
        lines.append(f"{format_vtt(cue.start)} --> {format_vtt(cue.end)}")
        lines.append(cue.text.strip())
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Advanced SubStation Alpha (.ass)
# --------------------------------------------------------------------------

_ASS_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
    " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
    " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
    " Alignment, MarginL, MarginR, MarginV, Encoding"
)

_ASS_EVENT_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
)


def to_ass(
    cues: Sequence[SubtitleCue],
    style: SubtitleStyle,
    *,
    play_res_x: int = ASS_PLAY_RES_X,
    play_res_y: int = ASS_PLAY_RES_Y,
    title: str = "Content Creator Platform",
) -> str:
    """Render a complete ASS script ready for the ``subtitles`` filter."""
    header = [
        "[Script Info]",
        f"Title: {title}",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        # Persian text is bidirectional; libass needs fribidi to lay it out.
        "YCbCr Matrix: None",
        "",
        "[V4+ Styles]",
        _ASS_STYLE_FORMAT,
        to_ass_style_line(style),
        "",
        "[Events]",
        _ASS_EVENT_FORMAT,
    ]

    events: list[str] = []
    for cue in _sorted(cues):
        events.append(
            "Dialogue: 0,"
            f"{format_ass(cue.start)},{format_ass(cue.end)},Default,,0,0,0,,"
            f"{_escape_ass_text(cue.text)}"
        )

    return "\n".join(header + events) + "\n"


def _escape_ass_text(text: str) -> str:
    """Make cue text safe for an ASS ``Dialogue`` line.

    Newlines become hard breaks; braces would otherwise open an override block
    and silently swallow the rest of the line.
    """
    cleaned = text.strip().replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\\", "\\\\")
    cleaned = cleaned.replace("{", "\\{").replace("}", "\\}")
    return cleaned.replace("\n", "\\N")


# --------------------------------------------------------------------------
# File output
# --------------------------------------------------------------------------


def write_subtitle_file(
    path: Path,
    cues: Sequence[SubtitleCue],
    style: SubtitleStyle,
    *,
    fmt: str | None = None,
) -> Path:
    """Serialise cues to ``path``, choosing the format from its suffix."""
    suffix = (fmt or path.suffix.lstrip(".")).lower()
    path.parent.mkdir(parents=True, exist_ok=True)

    if suffix == "srt":
        # BOM helps players that guess the encoding of Persian SRT wrongly.
        path.write_text(to_srt(cues), encoding="utf-8-sig", newline="\n")
    elif suffix == "vtt":
        path.write_text(to_vtt(cues), encoding="utf-8", newline="\n")
    elif suffix == "ass":
        path.write_text(to_ass(cues, style), encoding="utf-8", newline="\n")
    else:
        raise SubtitleError(
            f"unsupported subtitle format: {suffix!r}",
            user_message="این قالب زیرنویس پشتیبانی نمی‌شود.",
            details={"supported": ["srt", "vtt", "ass"]},
        )
    return path


def _sorted(cues: Iterable[SubtitleCue]) -> list[SubtitleCue]:
    return sorted(cues, key=lambda cue: (cue.start, cue.index))
