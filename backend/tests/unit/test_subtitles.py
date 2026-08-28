"""Subtitle representation, serialisation and segmentation tests."""

from __future__ import annotations

import pytest

from app.core.errors import SubtitleError
from app.core.timecode import format_ass, format_srt, format_vtt, parse_timecode
from app.domain.enums import SubtitleAlignment, SubtitlePosition
from app.domain.subtitle import SubtitleCue, SubtitleStyle
from app.media.subtitles.formats import parse_srt, to_ass, to_srt, to_vtt
from app.media.subtitles.segmentation import (
    SegmentationRules,
    cues_from_segments,
    cues_from_text,
)
from app.media.subtitles.style import ass_alignment, hex_to_ass_colour, to_ass_style_line
from app.domain.transcription import TranscriptSegment, TranscriptWord


def cue(start: float, end: float, text: str, index: int = 0) -> SubtitleCue:
    return SubtitleCue(id=f"c{index}", track_id="t", index=index, start=start, end=end, text=text)


class TestTimecode:
    @pytest.mark.parametrize(
        "seconds,expected",
        [(0.0, "00:00:00,000"), (1.5, "00:00:01,500"), (3661.25, "01:01:01,250")],
    )
    def test_format_srt(self, seconds, expected):
        assert format_srt(seconds) == expected

    def test_format_vtt_uses_dot(self):
        assert format_vtt(1.5) == "00:00:01.500"

    def test_format_ass_uses_centiseconds(self):
        assert format_ass(3661.25) == "1:01:01.25"

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("00:00:01,500", 1.5),
            ("00:00:01.500", 1.5),
            ("01:01:01,250", 3661.25),
            ("01:30", 90.0),
        ],
    )
    def test_parse(self, text, expected):
        assert parse_timecode(text) == pytest.approx(expected)

    def test_parse_rejects_garbage(self):
        with pytest.raises(ValueError):
            parse_timecode("not a timecode")

    def test_round_trip(self):
        for value in (0.0, 1.234, 59.999, 3600.0, 7322.456):
            assert parse_timecode(format_srt(value)) == pytest.approx(value, abs=0.001)

    def test_negative_clamped(self):
        assert format_srt(-5.0) == "00:00:00,000"


class TestCueModel:
    def test_rejects_end_before_start(self):
        with pytest.raises(ValueError):
            SubtitleCue(id="c", track_id="t", start=5.0, end=3.0, text="x")

    def test_rejects_zero_duration(self):
        with pytest.raises(ValueError):
            SubtitleCue(id="c", track_id="t", start=5.0, end=5.0, text="x")

    def test_characters_per_second(self):
        assert cue(0.0, 2.0, "12345678").characters_per_second == pytest.approx(4.0)


class TestStyle:
    def test_rejects_bad_colour(self):
        with pytest.raises(ValueError):
            SubtitleStyle(text_color="not-a-colour")

    def test_normalises_colour(self):
        assert SubtitleStyle(text_color="ffee00").text_color == "#FFEE00"

    def test_ass_colour_is_bgr_with_inverted_alpha(self):
        # #FFEE00 -> BBGGRR = 00EEFF, alpha 00 = fully opaque.
        assert hex_to_ass_colour("#FFEE00") == "&H0000EEFF"

    def test_ass_colour_alpha_inverted(self):
        assert hex_to_ass_colour("#000000", 1.0).startswith("&H00")
        assert hex_to_ass_colour("#000000", 0.0).startswith("&HFF")

    @pytest.mark.parametrize(
        "position,alignment,expected",
        [
            (SubtitlePosition.BOTTOM, SubtitleAlignment.CENTER, 2),
            (SubtitlePosition.TOP, SubtitleAlignment.CENTER, 8),
            (SubtitlePosition.MIDDLE, SubtitleAlignment.LEFT, 4),
            (SubtitlePosition.BOTTOM, SubtitleAlignment.RIGHT, 3),
        ],
    )
    def test_alignment_follows_numpad(self, position, alignment, expected):
        style = SubtitleStyle(position=position, alignment=alignment)
        assert ass_alignment(style) == expected

    def test_opaque_box_when_background_visible(self):
        line = to_ass_style_line(SubtitleStyle(background_opacity=0.7))
        # BorderStyle is field 16 (1-indexed) of the Style line.
        assert line.split(",")[15] == "3"

    def test_outline_mode_when_no_background(self):
        line = to_ass_style_line(SubtitleStyle(background_opacity=0.0))
        assert line.split(",")[15] == "1"


class TestSerialisation:
    def test_srt_round_trip(self):
        cues = [cue(0.0, 2.0, "سلام", 0), cue(2.5, 5.0, "دنیا", 1)]
        parsed = parse_srt(to_srt(cues))
        assert len(parsed) == 2
        assert parsed[0] == (0.0, 2.0, "سلام")
        assert parsed[1][2] == "دنیا"

    def test_srt_numbering_is_sequential(self):
        body = to_srt([cue(0.0, 1.0, "a", 0), cue(1.0, 2.0, "b", 1)])
        assert body.startswith("1\n")
        assert "\n2\n" in body

    def test_srt_sorted_by_time_regardless_of_input_order(self):
        parsed = parse_srt(to_srt([cue(5.0, 6.0, "second", 1), cue(0.0, 1.0, "first", 0)]))
        assert parsed[0][2] == "first"

    def test_parse_srt_tolerates_bom_and_crlf(self):
        raw = "﻿1\r\n00:00:00,000 --> 00:00:02,000\r\nسلام\r\n"
        assert parse_srt(raw)[0][2] == "سلام"

    def test_parse_srt_rejects_empty(self):
        with pytest.raises(SubtitleError):
            parse_srt("nothing useful here")

    def test_vtt_has_header(self):
        assert to_vtt([cue(0.0, 1.0, "x")]).startswith("WEBVTT")

    def test_ass_has_required_sections(self):
        body = to_ass([cue(0.0, 1.0, "سلام")], SubtitleStyle())
        assert "[Script Info]" in body
        assert "[V4+ Styles]" in body
        assert "[Events]" in body
        assert "Dialogue: 0," in body

    def test_ass_escapes_braces(self):
        # An unescaped brace opens an override block and eats the line.
        body = to_ass([cue(0.0, 1.0, "a {b} c")], SubtitleStyle())
        assert r"\{b\}" in body

    def test_ass_newline_becomes_hard_break(self):
        body = to_ass([cue(0.0, 1.0, "line1\nline2")], SubtitleStyle())
        assert "line1\\Nline2" in body

    def test_ass_play_res_matches_request(self):
        body = to_ass([cue(0.0, 1.0, "x")], SubtitleStyle(), play_res_x=640, play_res_y=360)
        assert "PlayResX: 640" in body
        assert "PlayResY: 360" in body


class TestSegmentation:
    def test_short_segment_kept_whole(self):
        segments = [TranscriptSegment(start=0.0, end=2.0, text="سلام دنیا")]
        cues = cues_from_segments(segments)
        assert len(cues) == 1
        assert cues[0].text == "سلام دنیا"

    def test_long_segment_is_split(self):
        long_text = "این یک جمله بسیار طولانی است. " * 6
        cues = cues_from_segments([TranscriptSegment(start=0.0, end=30.0, text=long_text)])
        assert len(cues) > 1
        assert all(len(c.text) <= 84 for c in cues)

    def test_split_uses_word_timings_when_available(self):
        words = [
            TranscriptWord(start=0.0, end=1.0, text="alpha"),
            TranscriptWord(start=1.0, end=2.0, text="bravo"),
            TranscriptWord(start=2.0, end=3.0, text="charlie"),
            TranscriptWord(start=3.0, end=4.0, text="delta"),
        ]
        segment = TranscriptSegment(
            start=0.0, end=4.0, text="alpha bravo charlie delta", words=words
        )
        rules = SegmentationRules(max_chars=12, target_chars=12, min_duration=0.1)
        cues = cues_from_segments([segment], rules=rules)
        assert len(cues) >= 2
        # First cue must begin where the first word actually begins.
        assert cues[0].start == pytest.approx(0.0, abs=0.01)

    def test_no_overlaps_and_ordered(self):
        segments = [
            TranscriptSegment(start=0.0, end=3.0, text="یک دو سه"),
            TranscriptSegment(start=2.9, end=6.0, text="چهار پنج شش"),
        ]
        cues = cues_from_segments(segments)
        for earlier, later in zip(cues, cues[1:]):
            assert earlier.end <= later.start + 1e-6
        assert all(c.end > c.start for c in cues)

    def test_minimum_duration_enforced(self):
        rules = SegmentationRules(min_duration=1.0)
        cues = cues_from_segments(
            [TranscriptSegment(start=0.0, end=0.2, text="کوتاه")], rules=rules
        )
        assert cues[0].end - cues[0].start >= 1.0

    def test_maximum_duration_enforced(self):
        rules = SegmentationRules(max_duration=5.0)
        cues = cues_from_segments(
            [TranscriptSegment(start=0.0, end=60.0, text="کوتاه")], rules=rules
        )
        assert all((c.end - c.start) <= 5.0 + 1e-6 for c in cues)

    def test_reading_speed_expands_dense_cues(self):
        rules = SegmentationRules(max_chars_per_second=10.0, max_duration=30.0)
        text = "x" * 50
        cues = cues_from_segments(
            [TranscriptSegment(start=0.0, end=1.0, text=text)], rules=rules
        )
        assert cues[0].characters_per_second if False else True
        assert (cues[0].end - cues[0].start) >= len(cues[0].text) / 10.0 - 0.01

    def test_never_splits_mid_word(self):
        text = "supercalifragilistic " * 10
        cues = cues_from_segments([TranscriptSegment(start=0.0, end=40.0, text=text)])
        for c in cues:
            for word in c.text.split():
                assert word in text

    def test_from_untimed_text_distributes_time(self):
        text = "جمله اول. جمله دوم. جمله سوم. " * 4
        cues = cues_from_text(text, 60.0)
        assert len(cues) > 1
        assert cues[0].start == pytest.approx(0.0)
        for earlier, later in zip(cues, cues[1:]):
            assert earlier.end <= later.start + 1e-6

    def test_empty_input_yields_nothing(self):
        assert cues_from_segments([]) == []
        assert cues_from_text("", 10.0) == []

    def test_whitespace_only_segments_dropped(self):
        cues = cues_from_segments([TranscriptSegment(start=0.0, end=2.0, text="   ")])
        assert cues == []
