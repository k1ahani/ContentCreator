"""Re-timing an existing subtitle track.

Segmentation (``segmentation.py``) decides *what text goes in a cue* when a
track is first built. This module decides *when an existing cue appears*, for
a track whose text is already final - the case the timeline editor exists to
fix, and the case a raw subtitle file lifted out of a video-generation step
always lands in: the words are right, the timings are not.

Two independent ways to fix that, deliberately kept separate because they
answer different questions:

**Audio alignment** (:func:`align_to_words`) - "when is each of these words
actually spoken?" The speech-recognition engine measures word timings from the
project's own audio, and the existing cue text is matched against that word
stream with :class:`difflib.SequenceMatcher`. Cues that match take the real
measured times of the words they matched; cues that do not are interpolated
between their matched neighbours. This only works when the subtitle text and
the audio are the same language and roughly the same words - which is exactly
the raw-subtitle case, and exactly *not* the translated-subtitle case.

**Speech distribution** (:func:`distribute_over_speech`) - the fallback when
matching fails (a translated track, a heavily rewritten one, an engine that
mis-heard most of it). Cue text is distributed by character count across the
*speech regions* the engine found rather than across the whole file, so
silence, music and gaps between speakers no longer eat subtitle time. Still
approximate, and reported as such, but structurally better than spreading text
evenly over a duration that is half silence.

**Batch retiming** (:func:`retime`) - no media analysis at all, just
arithmetic over the whole track at once: shift everything, scale everything,
repack everything at a chosen reading speed, or stretch the track to end at a
given time. This is what the user reaches for when they can see the offset
themselves.

Every path in this module - all four retime modes, both alignment paths - ends
in :func:`sanitize`. That is not a tidiness convention: an unsanitised timing
write is what produces the render artefacts this module exists to avoid. See
that function's docstring.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, replace

from app.domain.enums import SubtitleRetimeMode
from app.domain.subtitle import (
    RetimeOptions,
    RetimeReport,
    SubtitleCue,
    TimingRules,
)
from app.domain.transcription import TranscriptSegment, TranscriptWord

#: Below this fraction of matched cue words, alignment is not trustworthy and
#: the caller falls back to speech distribution. Chosen deliberately low: a
#: transcript of noisy audio can mis-hear half the words and still place the
#: other half correctly, which is enough to anchor the track - but at a third
#: or less the "matches" are mostly coincidental short words.
MIN_ALIGNMENT_COVERAGE = 0.35

#: Word-level matches shorter than this are ignored when they stand alone.
#: Persian "را"/"از" and English "a"/"to" match almost anywhere; letting an
#: isolated one anchor a cue drags it to a random point in the file.
_MIN_ANCHOR_TOKEN_CHARS = 2

#: Everything that is not an alphanumeric character in any script. ``\w`` is
#: Unicode-aware here, so Persian letters and digits survive while Latin *and*
#: Persian punctuation (``.``, ``،``, ``؟``) are stripped - a transcript and a
#: subtitle almost never punctuate the same word the same way.
_PUNCTUATION = re.compile(r"[\W_]+", re.UNICODE)
#: Persian/Arabic diacritics and the zero-width non-joiner, none of which are
#: pronounced and none of which the ASR engine reliably emits.
_INVISIBLE = re.compile(r"[ً-ْٰ‌‍‎‏]")

#: Arabic forms that mean the same letter as their Persian counterpart. A
#: transcript and a hand-typed subtitle routinely disagree on these, and
#: treating them as different characters would fail every match on the word.
_LETTER_FOLD = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا",
                              "إ": "ا", "آ": "ا", "ؤ": "و", "ئ": "ی"})

#: Persian and Arabic-Indic digits folded to ASCII, so "۱۲" matches "12".
_DIGIT_FOLD = str.maketrans(
    {**{chr(0x06F0 + i): str(i) for i in range(10)},
     **{chr(0x0660 + i): str(i) for i in range(10)}}
)


@dataclass(frozen=True, slots=True)
class TimedText:
    """One cue reduced to what re-timing needs: an identity, text, and a span.

    Deliberately not :class:`~app.domain.subtitle.SubtitleCue` - this module
    never sees style overrides, indices or track ids, and cannot accidentally
    write them.
    """

    key: str
    text: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(slots=True)
class AlignmentStats:
    """How well cue text matched the words measured in the audio."""

    #: Cue words that found a match in the ASR word stream.
    matched_words: int = 0
    total_words: int = 0
    #: Cues that got at least one real measured anchor.
    anchored_cues: int = 0
    #: Cues placed by interpolation between anchored neighbours.
    interpolated_cues: int = 0

    @property
    def coverage(self) -> float:
        return self.matched_words / self.total_words if self.total_words else 0.0


@dataclass(slots=True)
class TimingAdjustments:
    """Running tally of what :func:`sanitize` had to correct.

    Passed in by the caller and filled in as passes run, so a job that
    sanitises in more than one place (align, then interpolate, then clamp)
    reports one honest total rather than only the last pass's.
    """

    overlaps_fixed: int = 0
    durations_adjusted: int = 0
    clamped: int = 0


# --------------------------------------------------------------------------
# Hygiene
# --------------------------------------------------------------------------


def sanitize(
    items: list[TimedText],
    rules: TimingRules,
    adjustments: TimingAdjustments | None = None,
) -> list[TimedText]:
    """Force a timing list into a shape that renders cleanly.

    Everything here exists because of a specific way a burned-in render goes
    wrong, not because tidy numbers are nicer:

    * **Overlaps.** libass draws every cue whose span covers the current
      frame, so two overlapping cues are two stacked subtitle boxes - the most
      visible artefact of a bad sync, and the one a naive "shift everything"
      produces the moment two cues cross. Each cue is pushed to start at least
      ``gap`` after the previous one ends.
    * **Sub-frame durations.** A cue lasting 40ms flashes for one frame.
      Worse, a cue whose end lands on or before its start violates the
      ``end_seconds > start_seconds`` CHECK on ``subtitle_cues`` and the write
      fails outright - so ``min_duration`` is a correctness floor, not a
      preference.
    * **Runaway durations.** A cue held for a minute because the next one was
      dropped reads as a frozen frame.
    * **Overrunning the media.** A cue starting after the video ends is
      invisible in the render but still shows in the editor's timeline, which
      is how a "the sync worked, but the last three lines vanished" report
      happens. Cues are clamped inside ``media_duration`` when it is known.

    Order is preserved as given: the caller decides sequence (cue index),
    never this function, which only moves times.
    """
    tally = adjustments if adjustments is not None else TimingAdjustments()
    if not items:
        return []

    ceiling = rules.media_duration if rules.media_duration else None
    result: list[TimedText] = []
    previous_end = 0.0

    for position, item in enumerate(items):
        start = max(0.0, item.start)
        end = item.end

        # Clamp before de-overlapping, not after. The other order lets the
        # clamp pull two cues back onto the same final instant and hand back an
        # overlap this function had already resolved - re-creating the exact
        # artefact it exists to prevent.
        if ceiling is not None and end > ceiling:
            end = ceiling
            start = min(start, max(0.0, end - rules.min_duration))
            tally.clamped += 1

        if position > 0:
            floor = previous_end + rules.gap
            if start < floor:
                # Push the start clear of the previous cue but leave the end
                # where it was, so the collision is absorbed by this one cue
                # instead of cascading down the rest of the track. Carrying the
                # end forward instead would make every later cue land late, and
                # would let an operation with an explicit target - "stretch so
                # the track ends at 10s" - finish past its own target.
                # The end only moves when there is genuinely no room left.
                start = floor
                end = max(end, start + rules.min_duration)
                tally.overlaps_fixed += 1

        duration = end - start
        if duration < rules.min_duration:
            # Ordering wins over the media ceiling in the one case where they
            # conflict: more cues than the media has room for. A cue extending
            # past the end of the video is simply not drawn, while two cues
            # stacked on the same instant is a visible defect in the render.
            end = start + rules.min_duration
            tally.durations_adjusted += 1
        elif duration > rules.max_duration:
            end = start + rules.max_duration
            tally.durations_adjusted += 1

        if end <= start:
            # Last line of defence for the ``end_seconds > start_seconds``
            # CHECK on subtitle_cues; reaching it means min_duration was
            # somehow zero.
            end = start + max(rules.min_duration, 0.001)

        result.append(replace(item, start=round(start, 3), end=round(end, 3)))
        previous_end = end

    return result


def build_report(
    mode: str,
    before: list[TimedText],
    after: list[TimedText],
    adjustments: TimingAdjustments | None = None,
) -> RetimeReport:
    """Compare two timing lists into the report the UI shows."""
    original = {item.key: item for item in before}
    changed = 0
    max_shift = 0.0

    for item in after:
        previous = original.get(item.key)
        if previous is None:
            continue
        shift = abs(item.start - previous.start)
        if shift > 0.001 or abs(item.end - previous.end) > 0.001:
            changed += 1
        max_shift = max(max_shift, shift)

    tally = adjustments or TimingAdjustments()
    return RetimeReport(
        mode=mode,
        cue_count=len(after),
        changed_count=changed,
        overlaps_fixed=tally.overlaps_fixed,
        durations_adjusted=tally.durations_adjusted,
        clamped_count=tally.clamped,
        max_shift_seconds=round(max_shift, 3),
        first_start=round(after[0].start, 3) if after else 0.0,
        last_end=round(after[-1].end, 3) if after else 0.0,
    )


#: Hygiene rules used immediately before a burn-in render.
#:
#: Deliberately far looser than the retiming rules. A render must not quietly
#: re-time what the user placed by hand in the timeline editor - if they held a
#: title card for twenty seconds, that is the intent, not a mistake to correct.
#: So the duration bounds are effectively disabled and only the two genuine
#: render artefacts are fixed: overlapping cues, and durations too small to
#: survive the ASS format at all.
#:
#: ``gap`` is one centisecond because that is the resolution of an ASS
#: timecode (``h:mm:ss.cc``). A smaller gap rounds two cues onto the same
#: centisecond boundary in the written script, which libass then draws
#: stacked - the overlap would come back at the very last step, after having
#: been resolved everywhere upstream.
RENDER_RULES = TimingRules(min_duration=0.04, max_duration=86400.0, gap=0.01)


def prepare_for_render(
    cues: list[SubtitleCue], *, rules: TimingRules = RENDER_RULES
) -> tuple[list[SubtitleCue], TimingAdjustments, int]:
    """Last check before cues are written into an ASS script and burned in.

    Two problems are fixed here and nowhere else, because both are invisible
    until the moment of rendering:

    * **Blank cues.** A cue with no text still emits a ``Dialogue`` line. With
      the default style (``background_opacity > 0`` -> ASS ``BorderStyle=3``,
      an opaque box) that line draws an **empty coloured box** on the video for
      its whole duration - a black bar appearing over the picture for no
      reason. Blank cues are dropped rather than rendered.
    * **Overlaps.** libass draws every cue covering the current frame, so two
      overlapping cues become two stacked subtitle boxes. Cues normally arrive
      here already sanitised, but a track can reach this point overlapping
      through a hand edit in the timeline, an imported file, or a track built
      before this pass existed.

    Returns the cues to render, what had to be adjusted, and how many blank
    cues were dropped, so the job can report all three in its console instead
    of silently changing the output.
    """
    populated = [cue for cue in cues if cue.text.strip()]
    dropped = len(cues) - len(populated)
    if not populated:
        return [], TimingAdjustments(), dropped

    adjustments = TimingAdjustments()
    cleaned = sanitize(
        [
            TimedText(key=cue.id, text=cue.text, start=cue.start, end=cue.end)
            for cue in populated
        ],
        rules,
        adjustments,
    )
    by_id = {item.key: item for item in cleaned}
    return (
        [
            cue.model_copy(update={"start": by_id[cue.id].start, "end": by_id[cue.id].end})
            for cue in populated
        ],
        adjustments,
        dropped,
    )


# --------------------------------------------------------------------------
# Batch retiming (no media analysis)
# --------------------------------------------------------------------------


def retime(
    items: list[TimedText], options: RetimeOptions
) -> tuple[list[TimedText], RetimeReport]:
    """Apply one batch operation to every cue, then sanitise the result."""
    if not items:
        return [], RetimeReport(mode=options.mode.value)

    if options.mode is SubtitleRetimeMode.SHIFT:
        moved = _shift(items, options.offset_seconds)
    elif options.mode is SubtitleRetimeMode.SCALE:
        moved = _scale(items, options.factor, options.anchor_seconds)
    elif options.mode is SubtitleRetimeMode.READING_SPEED:
        moved = _reading_speed(items, options)
    else:
        moved = _stretch(items, options.target_end_seconds)

    adjustments = TimingAdjustments()
    cleaned = sanitize(moved, options.rules, adjustments)
    return cleaned, build_report(options.mode.value, items, cleaned, adjustments)


def _shift(items: list[TimedText], offset: float) -> list[TimedText]:
    """Move the whole track by a signed offset.

    Times clamp at zero rather than going negative, which the domain model
    rejects outright. The consequence is worth stating plainly because it
    surprises people: a cue already near the start of the video is *shortened*
    by a large negative shift rather than moved, since its start cannot go
    below zero while its end still moves. Every other cue keeps its duration
    and its spacing, so the track stays in sync with itself; only the ones
    pressed against zero absorb the difference. This matches what desktop
    subtitle editors do, and the alternative - refusing to shift at all
    because one cue sits at zero - would be worse.
    """
    return [
        replace(item, start=max(0.0, item.start + offset), end=max(0.0, item.end + offset))
        for item in items
    ]


def _scale(items: list[TimedText], factor: float, anchor: float) -> list[TimedText]:
    """Multiply every timing around ``anchor``, which stays where it is.

    Anchoring matters: scaling around zero moves the very first cue too, so a
    track that starts correctly and drifts later cannot be fixed without also
    re-shifting it. Anchoring at the first cue's start fixes drift alone.
    """
    return [
        replace(
            item,
            start=max(0.0, anchor + (item.start - anchor) * factor),
            end=max(0.0, anchor + (item.end - anchor) * factor),
        )
        for item in items
    ]


def _reading_speed(items: list[TimedText], options: RetimeOptions) -> list[TimedText]:
    """Repack the track back to back, each cue held long enough to read.

    This is the "subtitle display speed" control: duration comes from the
    cue's own character count divided by the target characters-per-second, so
    a long line stays up longer than a short one instead of every cue getting
    the same slice. Cues are then laid end to end from ``start_seconds``,
    which makes the operation deterministic - running it twice with the same
    settings produces the same track.
    """
    cursor = options.start_seconds if options.start_seconds is not None else items[0].start
    cursor = max(0.0, cursor)
    rules = options.rules
    result: list[TimedText] = []

    for item in items:
        characters = len(item.text.strip())
        duration = characters / options.chars_per_second if characters else rules.min_duration
        duration = min(max(duration, rules.min_duration), rules.max_duration)
        result.append(replace(item, start=cursor, end=cursor + duration))
        cursor += duration + rules.gap

    return result


def _stretch(items: list[TimedText], target_end: float | None) -> list[TimedText]:
    """Scale the track so its last cue ends at ``target_end``.

    Expressed in terms of the existing span rather than a factor, because
    "make the subtitles finish when the video does" is the question a user
    actually has; the factor is derived from it.
    """
    if not target_end:
        return list(items)

    origin = items[0].start
    current_end = max(item.end for item in items)
    span = current_end - origin
    if span <= 0:
        return list(items)

    return _scale(items, (target_end - origin) / span, origin)


# --------------------------------------------------------------------------
# Audio alignment
# --------------------------------------------------------------------------


def words_from_segments(segments: list[TranscriptSegment]) -> list[TranscriptWord]:
    """Flatten engine segments into one word stream with timings.

    Uses the engine's own word timings when it produced them (faster-whisper
    does). When it did not, a segment's span is divided among its words in
    proportion to their length - approximate, but still anchored to a real
    measured segment boundary at both ends, which is what alignment needs.
    """
    words: list[TranscriptWord] = []

    for segment in segments:
        measured = [word for word in segment.words if word.text.strip()]
        if measured:
            words.extend(measured)
            continue

        tokens = segment.text.split()
        if not tokens:
            continue
        total = sum(len(token) for token in tokens) or 1
        cursor = segment.start
        span = max(segment.duration, 0.0)
        for token in tokens:
            share = span * (len(token) / total)
            words.append(
                TranscriptWord(start=cursor, end=cursor + share, text=token)
            )
            cursor += share

    return words


def align_to_words(
    items: list[TimedText],
    words: list[TranscriptWord],
    rules: TimingRules,
    adjustments: TimingAdjustments | None = None,
) -> tuple[list[TimedText], AlignmentStats] | None:
    """Re-time cues from measured word timings by matching their text.

    Both sides are reduced to a flat list of normalised tokens and matched
    with :class:`difflib.SequenceMatcher`, which finds the longest matching
    blocks and tolerates the words the engine mis-heard, dropped or added -
    unlike a positional zip, which would desynchronise permanently at the
    first mistake.

    Returns ``None`` when too little of the cue text matched to trust the
    result (see :data:`MIN_ALIGNMENT_COVERAGE`); the caller then falls back to
    :func:`distribute_over_speech` rather than writing confident-looking times
    derived from coincidental matches.
    """
    cue_tokens: list[str] = []
    #: Which cue each flattened token came from.
    token_owner: list[int] = []
    for index, item in enumerate(items):
        for token in _tokenise(item.text):
            cue_tokens.append(token)
            token_owner.append(index)

    audio_tokens: list[str] = []
    token_times: list[tuple[float, float]] = []
    for word in words:
        token = _normalise_token(word.text)
        if not token:
            continue
        audio_tokens.append(token)
        token_times.append((word.start, word.end))

    if not cue_tokens or not audio_tokens:
        return None

    stats = AlignmentStats(total_words=len(cue_tokens))
    #: Per cue, the measured spans of every token that matched.
    hits: list[list[tuple[float, float]]] = [[] for _ in items]

    matcher = difflib.SequenceMatcher(None, cue_tokens, audio_tokens, autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            cue_position = block.a + offset
            audio_position = block.b + offset
            # A one-character function word matching in isolation is noise;
            # inside a run of two or more it is real evidence.
            if block.size < 2 and len(cue_tokens[cue_position]) < _MIN_ANCHOR_TOKEN_CHARS:
                continue
            hits[token_owner[cue_position]].append(token_times[audio_position])
            stats.matched_words += 1

    if stats.coverage < MIN_ALIGNMENT_COVERAGE:
        return None

    anchored: list[TimedText | None] = []
    for item, spans in zip(items, hits):
        if spans:
            anchored.append(
                replace(item, start=min(s for s, _ in spans), end=max(e for _, e in spans))
            )
            stats.anchored_cues += 1
        else:
            anchored.append(None)

    placed = _interpolate_gaps(items, anchored, rules)
    stats.interpolated_cues = len(items) - stats.anchored_cues
    return sanitize(placed, rules, adjustments), stats


def _interpolate_gaps(
    items: list[TimedText],
    anchored: list[TimedText | None],
    rules: TimingRules,
) -> list[TimedText]:
    """Place unmatched cues between their matched neighbours.

    An unmatched run is given the time between the previous anchor's end and
    the next anchor's start, divided among the cues by character count - the
    same honest proportional rule the untimed-text path in ``segmentation.py``
    uses, but over a span that is bounded by two real measured points instead
    of the whole file. Runs at the very start or end of the track extrapolate
    from the single anchor they have.
    """
    result: list[TimedText | None] = list(anchored)
    position = 0

    while position < len(result):
        if result[position] is not None:
            position += 1
            continue

        run_end = position
        while run_end < len(result) and result[run_end] is None:
            run_end += 1

        previous = result[position - 1] if position > 0 else None
        following = result[run_end] if run_end < len(result) else None

        if previous is not None and following is not None:
            span_start, span_end = previous.end + rules.gap, following.start - rules.gap
        elif previous is not None:
            span_start = previous.end + rules.gap
            span_end = span_start + _natural_span(items[position:run_end], rules)
        elif following is not None:
            span_end = max(0.0, following.start - rules.gap)
            span_start = max(0.0, span_end - _natural_span(items[position:run_end], rules))
        else:
            # Nothing matched anywhere; the caller's coverage check should have
            # rejected this already, so keep the original times untouched.
            for index in range(position, run_end):
                result[index] = items[index]
            position = run_end
            continue

        available = max(span_end - span_start, rules.min_duration * (run_end - position))
        chunk = items[position:run_end]
        total_chars = sum(max(len(item.text.strip()), 1) for item in chunk)
        cursor = span_start

        for offset, item in enumerate(chunk):
            share = max(len(item.text.strip()), 1) / total_chars
            duration = max(available * share - rules.gap, rules.min_duration)
            result[position + offset] = replace(item, start=cursor, end=cursor + duration)
            cursor += duration + rules.gap

        position = run_end

    return [item for item in result if item is not None]


def _natural_span(chunk: list[TimedText], rules: TimingRules) -> float:
    """How long a run of cues would take to read, used when only one side of
    the run has a measured anchor to extrapolate from."""
    return sum(
        min(max(len(item.text.strip()) / 15.0, rules.min_duration), rules.max_duration)
        + rules.gap
        for item in chunk
    )


# --------------------------------------------------------------------------
# Speech distribution (alignment fallback)
# --------------------------------------------------------------------------


def distribute_over_speech(
    items: list[TimedText],
    segments: list[TranscriptSegment],
    rules: TimingRules,
    adjustments: TimingAdjustments | None = None,
) -> list[TimedText]:
    """Spread cue text across the regions where someone is actually speaking.

    Used when cue text cannot be matched to the audio - a translated track is
    the normal case. Character-count distribution is still approximate, but
    distributing over *measured speech spans* rather than over the file's
    whole duration means subtitles no longer run through the silent intro, the
    music bed or the pause between speakers. That difference is usually worth
    several seconds of drift by the middle of a video.
    """
    spans = _speech_spans(segments)
    if not spans or not items:
        return sanitize(items, rules, adjustments)

    total_speech = sum(end - start for start, end in spans)
    if total_speech <= 0:
        return sanitize(items, rules, adjustments)

    total_chars = sum(max(len(item.text.strip()), 1) for item in items)
    result: list[TimedText] = []
    consumed = 0.0

    for item in items:
        share = max(len(item.text.strip()), 1) / total_chars
        length = total_speech * share
        result.append(
            replace(
                item,
                start=_speech_time_to_wall(consumed, spans, closing=False),
                end=_speech_time_to_wall(consumed + length, spans, closing=True),
            )
        )
        consumed += length

    return sanitize(result, rules, adjustments)


def _speech_spans(segments: list[TranscriptSegment]) -> list[tuple[float, float]]:
    """Merge engine segments into non-overlapping speech regions in order."""
    ordered = sorted(
        ((segment.start, segment.end) for segment in segments if segment.end > segment.start),
        key=lambda span: span[0],
    )
    merged: list[tuple[float, float]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _speech_time_to_wall(
    offset: float, spans: list[tuple[float, float]], *, closing: bool
) -> float:
    """Convert a position measured in speech-only seconds to a wall-clock time.

    Walking the spans rather than interpolating linearly is the whole point:
    the silence between spans costs zero speech seconds but real wall seconds,
    which is exactly the drift this fallback removes.

    ``closing`` disambiguates the boundary case, where one offset has two
    correct answers. When a cue's speech range ends exactly where a span ends,
    the cue should *end* there (``closing=True``) - but the next cue, whose
    range starts at that same offset, should *start* at the beginning of the
    following span, after the silence, not at the end of this one. Collapsing
    both to one rule is what makes the cue after a pause either stretch across
    the whole silence or begin before the speaker does.
    """
    remaining = max(0.0, offset)
    for start, end in spans:
        length = end - start
        if remaining < length or (closing and remaining <= length):
            return start + remaining
        remaining -= length
    return spans[-1][1]


# --------------------------------------------------------------------------
# Text normalisation
# --------------------------------------------------------------------------


def _tokenise(text: str) -> list[str]:
    """Words of a cue, normalised for matching. Empty tokens are dropped."""
    return [token for token in (_normalise_token(part) for part in text.split()) if token]


def _normalise_token(token: str) -> str:
    """Reduce a word to the form both a transcript and a subtitle agree on.

    Persian text arrives from two very different sources here - an ASR engine
    and a human typing - and they disagree about zero-width non-joiners,
    Arabic versus Persian yeh/kaf, diacritics, and digit script. None of those
    differences are audible, so folding them all away is what lets a correct
    subtitle match its own audio instead of failing on orthography.
    """
    folded = unicodedata.normalize("NFKC", token).translate(_LETTER_FOLD)
    folded = folded.translate(_DIGIT_FOLD)
    folded = _INVISIBLE.sub("", folded)
    folded = _PUNCTUATION.sub("", folded)
    return folded.casefold()
