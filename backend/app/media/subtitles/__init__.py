"""Subtitle representation, serialisation and segmentation.

The domain model lives in ``app/domain/subtitle.py``; this package turns it
into files (``formats.py``), styles it (``style.py``) and builds it from a
transcript (``segmentation.py``).
"""

from app.media.subtitles.formats import (
    parse_srt,
    to_ass,
    to_srt,
    to_vtt,
    write_subtitle_file,
)
from app.media.subtitles.segmentation import (
    DEFAULT_RULES,
    SegmentationRules,
    cues_from_segments,
    cues_from_text,
)
from app.media.subtitles.style import hex_to_ass_colour, to_ass_style_line

__all__ = [
    "DEFAULT_RULES",
    "SegmentationRules",
    "cues_from_segments",
    "cues_from_text",
    "hex_to_ass_colour",
    "parse_srt",
    "to_ass",
    "to_ass_style_line",
    "to_srt",
    "to_vtt",
    "write_subtitle_file",
]
