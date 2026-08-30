"""Subtitle re-timing: batch retiming, audio alignment and render hygiene.

Separate from ``test_subtitles.py`` because it covers a different question.
That file asks "does a transcript become sensible cues?"; this one asks "does
an *existing* track, whose text is already final, end up on the right part of
the timeline?" - and, throughout, "can the result ever render badly?", which
is the property the whole module exists to guarantee.
"""

from __future__ import annotations

import pytest

from app.domain.enums import SubtitleRetimeMode
from app.domain.subtitle import RetimeOptions, SubtitleCue, TimingRules
from app.domain.transcription import TranscriptSegment, TranscriptWord
from app.media.subtitles.sync import (
    MIN_ALIGNMENT_COVERAGE,
    TimedText,
    align_to_words,
    distribute_over_speech,
    prepare_for_render,
    retime,
    sanitize,
    words_from_segments,
)


def timed(key: str, text: str, start: float, end: float) -> TimedText:
    return TimedText(key=key, text=text, start=start, end=end)


def assert_renderable(items: list[TimedText], rules: TimingRules) -> None:
    """The invariants every timing write must satisfy, asserted in one place.

    These are exactly the properties a burned-in render depends on: no cue may
    be empty or inverted (the database CHECK rejects it outright), and no two
    cues may be on screen together (libass would stack them).
    """
    for item in items:
        assert item.end > item.start, f"{item.key} has a non-positive duration"
    for earlier, later in zip(items, items[1:]):
        assert later.start >= earlier.end, f"{later.key} overlaps {earlier.key}"


class TestSanitize:
    RULES = TimingRules(min_duration=0.5, max_duration=6.0, gap=0.04)

    def test_separates_overlapping_cues(self):
        items = [timed("a", "one", 0.0, 3.0), timed("b", "two", 1.0, 4.0)]
        result = sanitize(items, self.RULES)
        assert_renderable(result, self.RULES)
        assert result[1].start == pytest.approx(3.04)

    def test_overlap_fix_does_not_cascade_to_later_cues(self):
        # Only the colliding cue moves; a cue that was already clear of its
        # neighbour stays exactly where the caller put it.
        items = [
            timed("a", "one", 0.0, 3.0),
            timed("b", "two", 1.0, 4.0),
            timed("c", "three", 10.0, 12.0),
        ]
        result = sanitize(items, self.RULES)
        assert result[2].start == 10.0
        assert result[2].end == 12.0

    def test_enforces_minimum_duration(self):
        result = sanitize([timed("a", "x", 1.0, 1.01)], self.RULES)
        assert result[0].end - result[0].start == pytest.approx(0.5)

    def test_enforces_maximum_duration(self):
        result = sanitize([timed("a", "x", 0.0, 90.0)], self.RULES)
        assert result[0].end - result[0].start == pytest.approx(6.0)

    def test_clamps_inside_the_media_duration(self):
        rules = TimingRules(min_duration=0.5, max_duration=6.0, media_duration=10.0)
        result = sanitize([timed("a", "x", 8.0, 30.0)], rules)
        assert result[0].end <= 10.0

    def test_never_produces_a_negative_start(self):
        result = sanitize([timed("a", "x", -5.0, -1.0)], self.RULES)
        assert result[0].start >= 0.0
        assert result[0].end > result[0].start

    def test_ordering_wins_over_the_media_ceiling(self):
        # More cues than the media can hold: they must stay separated even
        # though that means running past the end. An overlap is a visible
        # defect in the render; a cue past the end is simply not drawn.
        rules = TimingRules(min_duration=0.5, max_duration=6.0, media_duration=1.0)
        items = [timed(str(i), "x", 100.0 + i, 102.0 + i) for i in range(4)]
        result = sanitize(items, rules)
        assert_renderable(result, rules)

    def test_reports_what_it_changed(self):
        # One cue overlaps its predecessor *and* is far too short. The overlap
        # fix resolves both at once, so it is reported once - a defect counted
        # under two headings would overstate what happened.
        items = [timed("a", "one", 0.0, 3.0), timed("b", "two", 1.0, 1.05)]
        result, report = retime(
            items, RetimeOptions(mode=SubtitleRetimeMode.SHIFT, offset_seconds=0.0)
        )
        assert report.overlaps_fixed == 1
        assert report.changed_count == 1
        assert (result[1].end - result[1].start) >= RetimeOptions().rules.min_duration

    def test_counts_a_short_cue_that_did_not_also_overlap(self):
        items = [timed("a", "one", 0.0, 3.0), timed("b", "two", 10.0, 10.05)]
        _, report = retime(
            items, RetimeOptions(mode=SubtitleRetimeMode.SHIFT, offset_seconds=0.0)
        )
        assert report.overlaps_fixed == 0
        assert report.durations_adjusted == 1


class TestBatchRetime:
    RULES = TimingRules(min_duration=0.5, max_duration=20.0, gap=0.04)

    ITEMS = [
        timed("a", "اولین قطعه", 10.0, 12.0),
        timed("b", "دومین قطعه", 20.0, 22.0),
        timed("c", "سومین قطعه", 30.0, 32.0),
    ]

    def test_shift_moves_every_cue_by_the_offset(self):
        result, report = retime(
            self.ITEMS,
            RetimeOptions(
                mode=SubtitleRetimeMode.SHIFT, offset_seconds=-2.5, rules=self.RULES
            ),
        )
        assert [item.start for item in result] == [7.5, 17.5, 27.5]
        assert report.changed_count == 3
        assert report.max_shift_seconds == pytest.approx(2.5)

    def test_shift_clamps_at_zero_rather_than_going_negative(self):
        result, _ = retime(
            self.ITEMS,
            RetimeOptions(
                mode=SubtitleRetimeMode.SHIFT, offset_seconds=-100.0, rules=self.RULES
            ),
        )
        assert result[0].start == 0.0
        assert_renderable(result, self.RULES)

    def test_scale_leaves_the_anchor_in_place(self):
        result, _ = retime(
            self.ITEMS,
            RetimeOptions(
                mode=SubtitleRetimeMode.SCALE,
                factor=2.0,
                anchor_seconds=10.0,
                rules=self.RULES,
            ),
        )
        assert result[0].start == 10.0
        assert result[1].start == pytest.approx(30.0)
        assert result[2].start == pytest.approx(50.0)

    def test_scale_by_one_changes_nothing(self):
        result, report = retime(
            self.ITEMS,
            RetimeOptions(mode=SubtitleRetimeMode.SCALE, factor=1.0, rules=self.RULES),
        )
        assert [(i.start, i.end) for i in result] == [(10.0, 12.0), (20.0, 22.0), (30.0, 32.0)]
        assert report.changed_count == 0

    def test_reading_speed_gives_longer_text_more_time(self):
        items = [timed("short", "کوتاه", 0.0, 5.0), timed("long", "یک متن به‌مراتب طولانی‌تر", 5.0, 10.0)]
        result, _ = retime(
            items,
            RetimeOptions(
                mode=SubtitleRetimeMode.READING_SPEED,
                chars_per_second=5.0,
                start_seconds=0.0,
                rules=self.RULES,
            ),
        )
        assert (result[1].end - result[1].start) > (result[0].end - result[0].start)
        assert result[0].start == 0.0
        assert_renderable(result, self.RULES)

    def test_reading_speed_is_deterministic(self):
        options = RetimeOptions(
            mode=SubtitleRetimeMode.READING_SPEED,
            chars_per_second=8.0,
            start_seconds=1.0,
            rules=self.RULES,
        )
        once, _ = retime(self.ITEMS, options)
        twice, _ = retime(once, options)
        assert [(i.start, i.end) for i in once] == [(i.start, i.end) for i in twice]

    def test_slower_reading_speed_keeps_cues_on_screen_longer(self):
        fast, _ = retime(
            self.ITEMS,
            RetimeOptions(
                mode=SubtitleRetimeMode.READING_SPEED, chars_per_second=20.0, rules=self.RULES
            ),
        )
        slow, _ = retime(
            self.ITEMS,
            RetimeOptions(
                mode=SubtitleRetimeMode.READING_SPEED, chars_per_second=4.0, rules=self.RULES
            ),
        )
        assert (slow[0].end - slow[0].start) > (fast[0].end - fast[0].start)

    def test_stretch_ends_exactly_at_the_target(self):
        result, report = retime(
            self.ITEMS,
            RetimeOptions(
                mode=SubtitleRetimeMode.STRETCH, target_end_seconds=64.0, rules=self.RULES
            ),
        )
        assert report.last_end == pytest.approx(64.0)
        assert result[0].start == 10.0  # the first cue anchors the stretch

    def test_stretch_handles_a_target_before_the_current_end(self):
        result, report = retime(
            self.ITEMS,
            RetimeOptions(
                mode=SubtitleRetimeMode.STRETCH, target_end_seconds=20.0, rules=self.RULES
            ),
        )
        assert_renderable(result, self.RULES)
        assert report.last_end <= 20.5

    def test_every_mode_leaves_the_track_renderable(self):
        crowded = [timed(str(i), "متن نمونه", i * 0.3, i * 0.3 + 2.0) for i in range(12)]
        for options in (
            RetimeOptions(mode=SubtitleRetimeMode.SHIFT, offset_seconds=3.0),
            RetimeOptions(mode=SubtitleRetimeMode.SCALE, factor=0.25),
            RetimeOptions(mode=SubtitleRetimeMode.READING_SPEED, chars_per_second=30.0),
            RetimeOptions(mode=SubtitleRetimeMode.STRETCH, target_end_seconds=8.0),
        ):
            result, _ = retime(crowded, options)
            assert_renderable(result, options.rules)

    def test_text_is_never_touched(self):
        result, _ = retime(
            self.ITEMS,
            RetimeOptions(mode=SubtitleRetimeMode.SCALE, factor=3.0, rules=self.RULES),
        )
        assert [item.text for item in result] == [item.text for item in self.ITEMS]
        assert [item.key for item in result] == [item.key for item in self.ITEMS]

    def test_empty_track_is_not_an_error(self):
        result, report = retime([], RetimeOptions(mode=SubtitleRetimeMode.SHIFT))
        assert result == []
        assert report.cue_count == 0


class TestWordsFromSegments:
    def test_prefers_the_engines_own_word_timings(self):
        segment = TranscriptSegment(
            start=0.0,
            end=2.0,
            text="سلام دنیا",
            words=[
                TranscriptWord(start=0.1, end=0.5, text="سلام"),
                TranscriptWord(start=0.7, end=1.4, text="دنیا"),
            ],
        )
        words = words_from_segments([segment])
        assert [w.start for w in words] == [0.1, 0.7]

    def test_synthesises_word_timings_when_the_engine_gave_none(self):
        words = words_from_segments(
            [TranscriptSegment(start=0.0, end=4.0, text="یک دو سه چهار")]
        )
        assert len(words) == 4
        assert words[0].start == 0.0
        assert words[-1].end == pytest.approx(4.0)
        for earlier, later in zip(words, words[1:]):
            assert later.start >= earlier.start


class TestAudioAlignment:
    RULES = TimingRules(min_duration=0.3, max_duration=10.0, gap=0.04)

    def words(self, pairs) -> list[TranscriptWord]:
        return [TranscriptWord(start=s, end=e, text=t) for t, s, e in pairs]

    def test_cues_take_the_measured_times_of_their_words(self):
        items = [timed("a", "سلام دنیا", 0.0, 2.0), timed("b", "خوش آمدید", 2.0, 4.0)]
        words = self.words(
            [("سلام", 30.0, 30.4), ("دنیا", 30.5, 31.0),
             ("خوش", 45.0, 45.4), ("آمدید", 45.5, 46.0)]
        )
        result = align_to_words(items, words, self.RULES)
        assert result is not None
        placed, stats = result
        assert placed[0].start == pytest.approx(30.0)
        assert placed[0].end == pytest.approx(31.0)
        assert placed[1].start == pytest.approx(45.0)
        assert stats.coverage == 1.0
        assert stats.anchored_cues == 2

    def test_survives_words_the_engine_misheard(self):
        items = [
            timed("a", "سلام دنیا", 0.0, 1.0),
            timed("b", "امروز هوا خوب است", 1.0, 2.0),
            timed("c", "خداحافظ دوستان", 2.0, 3.0),
        ]
        # The middle of the transcript is wrong, plus a spurious extra word -
        # the exact failure a positional zip would never recover from.
        words = self.words(
            [("سلام", 10.0, 10.4), ("دنیا", 10.5, 11.0),
             ("اموز", 20.0, 20.4), ("هوا", 20.5, 21.0), ("عالیست", 21.1, 21.8),
             ("خداحافظ", 30.0, 30.6), ("دوستان", 30.7, 31.4)]
        )
        result = align_to_words(items, words, self.RULES)
        assert result is not None
        placed, _ = result
        assert placed[0].start == pytest.approx(10.0)
        assert placed[2].start == pytest.approx(30.0)
        assert_renderable(placed, self.RULES)

    def test_unmatched_cues_are_interpolated_between_their_neighbours(self):
        items = [
            timed("a", "سلام دنیا", 0.0, 1.0),
            timed("b", "متن کاملاً متفاوتی که شنیده نشده", 1.0, 2.0),
            timed("c", "خداحافظ دوستان", 2.0, 3.0),
        ]
        words = self.words(
            [("سلام", 10.0, 10.4), ("دنیا", 10.5, 11.0),
             ("چیز", 15.0, 15.4), ("دیگری", 15.5, 16.0),
             ("خداحافظ", 30.0, 30.6), ("دوستان", 30.7, 31.4)]
        )
        result = align_to_words(items, words, self.RULES)
        assert result is not None
        placed, stats = result
        assert stats.interpolated_cues == 1
        # The unmatched cue lands between its two anchored neighbours.
        assert 11.0 <= placed[1].start < placed[2].start
        assert_renderable(placed, self.RULES)

    def test_refuses_to_align_a_translated_track(self):
        # English cue text against Persian audio: nothing meaningful matches,
        # so alignment declines rather than inventing confident timings.
        items = [
            timed("a", "Hello world, welcome to the show", 0.0, 2.0),
            timed("b", "Today we discuss something entirely different", 2.0, 4.0),
        ]
        words = self.words(
            [("سلام", 10.0, 10.4), ("دنیا", 10.5, 11.0),
             ("امروز", 12.0, 12.6), ("درباره", 12.7, 13.2)]
        )
        assert align_to_words(items, words, self.RULES) is None

    def test_matches_across_orthographic_differences(self):
        # Arabic yeh/kaf, a zero-width non-joiner and Persian digits on one
        # side, their plain equivalents on the other: audibly identical, so
        # they must match.
        items = [timed("a", "كتاب‌های ۱۲ نفر", 0.0, 2.0)]
        words = self.words([("کتابهای", 5.0, 5.6), ("12", 5.7, 6.0), ("نفر", 6.1, 6.5)])
        result = align_to_words(items, words, self.RULES)
        assert result is not None
        placed, stats = result
        assert stats.coverage > MIN_ALIGNMENT_COVERAGE
        assert placed[0].start == pytest.approx(5.0)

    def test_ignores_punctuation_differences(self):
        items = [timed("a", "سلام، دنیا!", 0.0, 2.0)]
        words = self.words([("سلام", 8.0, 8.4), ("دنیا", 8.5, 9.0)])
        result = align_to_words(items, words, self.RULES)
        assert result is not None
        assert result[0][0].start == pytest.approx(8.0)

    def test_result_is_always_renderable(self):
        items = [timed(str(i), f"قطعه شماره {i}", i, i + 1) for i in range(6)]
        words = self.words(
            [(word, 5.0 + i * 0.5, 5.4 + i * 0.5)
             for i, word in enumerate(
                 ["قطعه", "شماره", "0", "قطعه", "شماره", "1", "قطعه", "شماره", "2"]
             )]
        )
        result = align_to_words(items, words, self.RULES)
        if result is not None:
            assert_renderable(result[0], self.RULES)


class TestSpeechDistribution:
    RULES = TimingRules(min_duration=0.3, max_duration=30.0, gap=0.04)

    def test_cues_land_inside_the_speech_regions_not_the_silence(self):
        items = [timed("a", "دوازده حرف", 0.0, 1.0), timed("b", "دوازده حرف", 1.0, 2.0)]
        segments = [
            TranscriptSegment(start=10.0, end=14.0, text="x"),
            TranscriptSegment(start=50.0, end=54.0, text="y"),
        ]
        result = distribute_over_speech(items, segments, self.RULES)
        assert result[0].start == pytest.approx(10.0)
        assert result[0].end == pytest.approx(14.0)
        # The second cue starts where the second speech region does, not in
        # the 36 seconds of silence between them.
        assert result[1].start == pytest.approx(50.0)
        assert_renderable(result, self.RULES)

    def test_longer_text_gets_a_bigger_share_of_the_speech(self):
        items = [timed("a", "کوتاه", 0.0, 1.0), timed("b", "یک متن بسیار طولانی‌تر از قبلی", 1.0, 2.0)]
        segments = [TranscriptSegment(start=0.0, end=60.0, text="x")]
        result = distribute_over_speech(items, segments, self.RULES)
        assert (result[1].end - result[1].start) > (result[0].end - result[0].start)

    def test_merges_overlapping_speech_segments(self):
        items = [timed("a", "متن", 0.0, 1.0)]
        segments = [
            TranscriptSegment(start=0.0, end=10.0, text="x"),
            TranscriptSegment(start=5.0, end=15.0, text="y"),
        ]
        result = distribute_over_speech(items, segments, self.RULES)
        assert result[0].start == 0.0
        assert result[0].end <= 15.0

    def test_no_speech_leaves_the_track_untouched_but_valid(self):
        items = [timed("a", "متن", 0.0, 1.0)]
        result = distribute_over_speech(items, [], self.RULES)
        assert_renderable(result, self.RULES)


class TestPrepareForRender:
    def cue(self, index: int, start: float, end: float, text: str) -> SubtitleCue:
        return SubtitleCue(
            id=f"c{index}", track_id="t", index=index, start=start, end=end, text=text
        )

    def test_drops_blank_cues_that_would_render_as_empty_boxes(self):
        cues = [
            self.cue(0, 0.0, 1.0, "متن"),
            self.cue(1, 2.0, 3.0, "   "),
            self.cue(2, 4.0, 5.0, "متن دیگر"),
        ]
        rendered, _, dropped = prepare_for_render(cues)
        assert dropped == 1
        assert [c.text for c in rendered] == ["متن", "متن دیگر"]

    def test_separates_overlapping_cues_before_they_reach_libass(self):
        cues = [self.cue(0, 0.0, 5.0, "اول"), self.cue(1, 2.0, 6.0, "دوم")]
        rendered, adjustments, _ = prepare_for_render(cues)
        assert adjustments.overlaps_fixed == 1
        assert rendered[1].start >= rendered[0].end

    def test_leaves_a_deliberately_long_cue_alone(self):
        # A twenty-second title card is intent, not a mistake: the render pass
        # must not silently re-time what the user placed by hand.
        cues = [self.cue(0, 0.0, 20.0, "کارت عنوان")]
        rendered, adjustments, _ = prepare_for_render(cues)
        assert rendered[0].end == 20.0
        assert adjustments.durations_adjusted == 0

    def test_preserves_cue_identity_and_style_overrides(self):
        cue = SubtitleCue(
            id="c0", track_id="t", index=0, start=0.0, end=1.0,
            text="متن", style_overrides={"font_size": 40},
        )
        rendered, _, _ = prepare_for_render([cue])
        assert rendered[0].id == "c0"
        assert rendered[0].style_overrides == {"font_size": 40}

    def test_a_track_of_only_blank_cues_renders_nothing(self):
        rendered, _, dropped = prepare_for_render(
            [self.cue(0, 0.0, 1.0, ""), self.cue(1, 2.0, 3.0, "  ")]
        )
        assert rendered == []
        assert dropped == 2

    def test_gap_survives_ass_centisecond_rounding(self):
        # ASS timecodes have centisecond resolution; a smaller gap than that
        # would round two cues back onto the same boundary in the written
        # script and libass would stack them again.
        cues = [self.cue(0, 0.0, 1.0, "اول"), self.cue(1, 0.5, 2.0, "دوم")]
        rendered, _, _ = prepare_for_render(cues)
        assert round(rendered[1].start, 2) > round(rendered[0].end, 2)
