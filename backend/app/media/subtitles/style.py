"""Subtitle style translation.

One :class:`~app.domain.subtitle.SubtitleStyle` drives two very different
renderers - CSS in the browser preview and an ASS style block in FFmpeg - so
the preview is trustworthy rather than decorative. This module owns the ASS
half; the CSS half lives in ``frontend/src/lib/subtitleStyle.ts`` and is kept
deliberately in step with it.

Two ASS details are easy to get wrong and worth stating plainly:

**Colour format.** ASS uses ``&HAABBGGRR``: byte order is reversed relative to
CSS, and the alpha byte is *inverted* - ``00`` is fully opaque, ``FF`` fully
transparent.

**Background boxes.** ASS has no separate "background colour" for text. A
filled box behind the text is ``BorderStyle=3`` (opaque box), and in that mode
libass fills the box with the **outline** colour, not ``BackColour``. So a
style with a visible background is emitted as ``BorderStyle=3`` with the
background colour in the outline slot; a style without one is emitted as
``BorderStyle=1`` with a real outline and drop shadow.
"""

from __future__ import annotations

from app.domain.enums import SubtitleAlignment, SubtitlePosition
from app.domain.subtitle import SubtitleStyle

#: ASS alignment values follow the numeric keypad layout.
_ALIGNMENT_MAP: dict[tuple[SubtitlePosition, SubtitleAlignment], int] = {
    (SubtitlePosition.BOTTOM, SubtitleAlignment.LEFT): 1,
    (SubtitlePosition.BOTTOM, SubtitleAlignment.CENTER): 2,
    (SubtitlePosition.BOTTOM, SubtitleAlignment.RIGHT): 3,
    (SubtitlePosition.MIDDLE, SubtitleAlignment.LEFT): 4,
    (SubtitlePosition.MIDDLE, SubtitleAlignment.CENTER): 5,
    (SubtitlePosition.MIDDLE, SubtitleAlignment.RIGHT): 6,
    (SubtitlePosition.TOP, SubtitleAlignment.LEFT): 7,
    (SubtitlePosition.TOP, SubtitleAlignment.CENTER): 8,
    (SubtitlePosition.TOP, SubtitleAlignment.RIGHT): 9,
}


def hex_to_ass_colour(hex_colour: str, opacity: float = 1.0) -> str:
    """Convert ``#RRGGBB`` plus 0..1 opacity to ``&HAABBGGRR``."""
    text = hex_colour.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"expected #RRGGBB, got {hex_colour!r}")
    red, green, blue = text[0:2], text[2:4], text[4:6]
    clamped = min(max(opacity, 0.0), 1.0)
    # ASS alpha is inverted: 0x00 opaque, 0xFF transparent.
    alpha = round((1.0 - clamped) * 255)
    return f"&H{alpha:02X}{blue}{green}{red}".upper()


def ass_alignment(style: SubtitleStyle) -> int:
    return _ALIGNMENT_MAP[(style.position, style.alignment)]


def to_ass_style_line(style: SubtitleStyle, *, name: str = "Default") -> str:
    """Render one ``Style:`` line for an ASS ``[V4+ Styles]`` section."""
    has_background = style.background_opacity > 0.0

    if has_background:
        border_style = 3
        outline_colour = hex_to_ass_colour(
            style.background_color, style.background_opacity
        )
        # In opaque-box mode this value is the padding around the glyphs.
        outline_width = max(style.outline_width, 4.0)
        shadow = 0.0
    else:
        border_style = 1
        outline_colour = hex_to_ass_colour(style.outline_color)
        outline_width = style.outline_width
        shadow = style.shadow_depth

    fields = [
        name,
        style.font_family,
        str(style.font_size),
        hex_to_ass_colour(style.text_color),          # PrimaryColour
        hex_to_ass_colour(style.text_color),          # SecondaryColour (karaoke)
        outline_colour,                                # OutlineColour / box fill
        hex_to_ass_colour("#000000", 0.5),            # BackColour (shadow)
        "-1" if style.bold else "0",
        "-1" if style.italic else "0",
        "0",                                           # Underline
        "0",                                           # StrikeOut
        "100",                                         # ScaleX
        "100",                                         # ScaleY
        "0",                                           # Spacing
        "0",                                           # Angle
        str(border_style),
        f"{outline_width:g}",
        f"{shadow:g}",
        str(ass_alignment(style)),
        str(style.margin_horizontal),                  # MarginL
        str(style.margin_horizontal),                  # MarginR
        str(style.margin_vertical),                    # MarginV
        "1",                                           # Encoding: default
    ]
    return "Style: " + ",".join(fields)


def css_font_stack(font_family: str) -> str:
    """Font stack used by the browser preview.

    Mirrors the fallback chain the renderer relies on, so a font that is
    missing on this machine degrades the same way in both places.
    """
    fallbacks = ["Vazirmatn", "Tahoma", "Segoe UI", "Arial", "sans-serif"]
    primary = font_family.strip()
    chain = [primary] + [name for name in fallbacks if name != primary]
    return ", ".join(f'"{name}"' if " " in name else name for name in chain)
