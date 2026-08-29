"""Turning a transcript into readable subtitle cues.

Two inputs are supported, and the difference matters:

* **Timed segments** from the speech-recognition engine. Timings are measured
  from the audio, so a cue split inherits real time boundaries - from word
  timings when the engine supplied them, and proportionally by character count
  when it did not. This is the normal path.
* **Plain text plus a total duration.** No measured timings exist, so cues are
  distributed by character count. Honest but approximate; the UI says so, and
  the timeline editor exists to fix it.

How a cue boundary is chosen is itself configurable
(:class:`~app.domain.enums.SubtitleSegmentationMode`, ``rules.mode``):

* ``AUTOMATIC`` (default) - the original behaviour: a character-length
  cascade preferring a sentence boundary, then a clause boundary, then a word
  boundary - never mid-word. The right default for most content.
* ``SENTENCE`` - one cue per complete sentence, never split further.
* ``SHORT`` / ``NORMAL`` / ``CUSTOM`` - a fixed number of words per cue
  instead of a character budget (3 / 6 / ``rules.words_per_cue``
  respectively) - useful for fast-paced or karaoke-style captioning, down to
  one word per cue.

Word-count and sentence modes are an explicit choice about chunk size, so
:func:`cues_from_segments` skips its usual "merge cues that turned out too
short to read" pass for them - re-merging a user's deliberate one-word cues
back together would silently override the setting they just picked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.enums import SubtitleSegmentationMode
from app.domain.subtitle import CueCreate
from app.domain.transcription import TranscriptSegment

#: Sentence-ending punctuation, Latin and Persian.
_SENTENCE_END = re.compile(r"[.!?۔؟]+[\s]*")
#: Clause boundaries, Latin and Persian.
_CLAUSE_BREAK = re.compile(r"[,;:،؛]+[\s]*")

#: Words per cue for the two named fixed-count modes. CUSTOM instead reads
#: ``SegmentationRules.words_per_cue`` directly - see ``_words_per_cue``.
_NAMED_WORD_COUNTS: dict[SubtitleSegmentationMode, int] = {
    SubtitleSegmentationMode.SHORT: 3,
    SubtitleSegmentationMode.NORMAL: 6,
}


@dataclass(frozen=True, slots=True)
class SegmentationRules:
    """Readability constraints applied when building cues."""

    #: Longest cue text before it must be split. Only consulted in
    #: ``AUTOMATIC`` mode - the other modes have their own notion of "too long".
    max_chars: int = 84
    #: Preferred single-line length; used when choosing a split point in
    #: ``AUTOMATIC`` mode.
    target_chars: int = 42
    #: A cue shorter than this is hard to notice.
    min_duration: float = 1.0
    #: A cue longer than this stays on screen too long.
    max_duration: float = 7.0
    #: Reading speed ceiling. Above ~21 characters per second most viewers
    #: cannot keep up.
    max_chars_per_second: float = 21.0
    #: Gap left between consecutive cues so they do not visually collide.
    gap: float = 0.04
    #: Segments shorter than this are merged into their neighbour. Only
    #: applied in ``AUTOMATIC`` mode - see the module docstring for why.
    merge_below: float = 0.8
    #: Which strategy decides where a cue boundary falls.
    mode: SubtitleSegmentationMode = SubtitleSegmentationMode.AUTOMATIC
    #: Exact words per cue when ``mode`` is ``CUSTOM``. Clamped to at least 1;
    #: ignored for every other mode.
    words_per_cue: int | None = None


DEFAULT_RULES = SegmentationRules()


def _words_per_cue(rules: SegmentationRules) -> int:
    """Resolve the target word count for a fixed-count mode."""
    if rules.mode == SubtitleSegmentationMode.CUSTOM:
        return max(1, rules.words_per_cue or 6)
    return _NAMED_WORD_COUNTS.get(rules.mode, 6)


def _is_fixed_word_count_mode(rules: SegmentationRules) -> bool:
    return rules.mode in (
        SubtitleSegmentationMode.SHORT,
        SubtitleSegmentationMode.NORMAL,
        SubtitleSegmentationMode.CUSTOM,
    )


def _chunk_text(text: str, rules: SegmentationRules) -> list[str]:
    """Break ``text`` into cue-sized chunks per the configured mode."""
    text = text.strip()
    if not text:
        return []

    if rules.mode == SubtitleSegmentationMode.SENTENCE:
        return _split_on(text, _SENTENCE_END)

    if _is_fixed_word_count_mode(rules):
        return _split_by_word_count(text, _words_per_cue(rules))

    return _split_text(text, rules)


def _needs_split(text: str, duration: float, rules: SegmentationRules) -> bool:
    """Whether ``text`` (measured over ``duration`` seconds) exceeds this
    mode's own notion of "one cue's worth" and must be chunked further."""
    if rules.mode == SubtitleSegmentationMode.SENTENCE:
        return len(_split_on(text, _SENTENCE_END)) > 1
    if _is_fixed_word_count_mode(rules):
        return len(text.split()) > _words_per_cue(rules)
    return len(text) > rules.max_chars or duration > rules.max_duration


def _split_by_word_count(text: str, words_per_cue: int) -> list[str]:
    """Pack exactly ``words_per_cue`` words into each chunk (the last chunk
    may have fewer). Never breaks a word - splits only on whitespace."""
    words = text.split()
    if not words:
        return []
    return [
        " ".join(words[i : i + words_per_cue])
        for i in range(0, len(words), words_per_cue)
    ]


def cues_from_segments(
    segments: list[TranscriptSegment],
    *,
    rules: SegmentationRules = DEFAULT_RULES,
) -> list[CueCreate]:
    """Build cues from engine segments, preserving measured timings."""
    cues: list[CueCreate] = []

    for segment in segments:
        text = _normalise(segment.text)
        if not text:
            continue
        if not _needs_split(text, segment.duration, rules):
            cues.append(CueCreate(start=segment.start, end=segment.end, text=text))
            continue
        cues.extend(_split_segment(segment, text, rules))

    # An explicit word-count/sentence choice is a deliberate chunk size;
    # re-merging short results back together would silently undo it.
    if rules.mode == SubtitleSegmentationMode.AUTOMATIC:
        cues = _merge_tiny(cues, rules)
    return _enforce_timing(cues, rules)


def cues_from_text(
    text: str,
    total_duration: float,
    *,
    rules: SegmentationRules = DEFAULT_RULES,
) -> list[CueCreate]:
    """Build cues from untimed text by distributing time across characters."""
    chunks = _chunk_text(_normalise(text), rules)
    if not chunks:
        return []

    total_chars = sum(len(chunk) for chunk in chunks) or 1
    cues: list[CueCreate] = []
    cursor = 0.0

    for chunk in chunks:
        share = len(chunk) / total_chars
        duration = max(rules.min_duration, total_duration * share)
        cues.append(CueCreate(start=cursor, end=cursor + duration, text=chunk))
        cursor += duration + rules.gap

    return _enforce_timing(cues, rules)


# --------------------------------------------------------------------------
# Splitting
# --------------------------------------------------------------------------


def _split_segment(
    segment: TranscriptSegment, text: str, rules: SegmentationRules
) -> list[CueCreate]:
    """Split one over-long segment, keeping timings as accurate as possible."""
    chunks = _chunk_text(text, rules)
    if len(chunks) <= 1:
        return [CueCreate(start=segment.start, end=segment.end, text=text)]

    if segment.words:
        timed = _split_by_words(segment, chunks)
        if timed:
            return timed

    # No word timings: distribute the segment's own span by character count.
    total_chars = sum(len(chunk) for chunk in chunks) or 1
    cues: list[CueCreate] = []
    cursor = segment.start
    span = max(segment.duration, rules.min_duration * len(chunks))

    for chunk in chunks:
        duration = span * (len(chunk) / total_chars)
        cues.append(CueCreate(start=cursor, end=cursor + duration, text=chunk))
        cursor += duration
    return cues


def _split_by_words(
    segment: TranscriptSegment, chunks: list[str]
) -> list[CueCreate] | None:
    """Align chunks to word timings by walking both in order.

    Returns ``None`` when the alignment does not consume every chunk, in which
    case the caller falls back to proportional timing rather than emitting
    silently wrong times.
    """
    words = [word for word in segment.words if word.text.strip()]
    if not words:
        return None

    cues: list[CueCreate] = []
    word_index = 0

    for chunk in chunks:
        remaining = len(_strip_spaces(chunk))
        if remaining == 0:
            continue
        start_index = word_index
        consumed = 0
        while word_index < len(words) and consumed < remaining:
            consumed += len(_strip_spaces(words[word_index].text))
            word_index += 1
        if word_index == start_index:
            return None
        cues.append(
            CueCreate(
                start=words[start_index].start,
                end=words[word_index - 1].end,
                text=chunk,
            )
        )

    return cues if cues else None


def _split_text(text: str, rules: SegmentationRules) -> list[str]:
    """Break text into readable chunks at the best available boundary."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= rules.max_chars:
        return [text]

    chunks: list[str] = []
    for sentence in _split_on(text, _SENTENCE_END):
        if len(sentence) <= rules.max_chars:
            chunks.append(sentence)
            continue
        for clause in _split_on(sentence, _CLAUSE_BREAK):
            if len(clause) <= rules.max_chars:
                chunks.append(clause)
            else:
                chunks.extend(_split_on_words(clause, rules))
    return [chunk for chunk in (c.strip() for c in chunks) if chunk]


def _split_on(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Split while keeping the delimiter attached to the preceding piece."""
    pieces: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        piece = text[cursor : match.end()].strip()
        if piece:
            pieces.append(piece)
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        pieces.append(tail)
    return pieces or [text.strip()]


def _split_on_words(text: str, rules: SegmentationRules) -> list[str]:
    """Last resort: pack words up to the target length. Never breaks a word."""
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    length = 0

    for word in words:
        addition = len(word) + (1 if current else 0)
        if current and length + addition > rules.target_chars:
            chunks.append(" ".join(current))
            current, length = [word], len(word)
        else:
            current.append(word)
            length += addition

    if current:
        chunks.append(" ".join(current))
    return chunks


# --------------------------------------------------------------------------
# Timing hygiene
# --------------------------------------------------------------------------


def _merge_tiny(cues: list[CueCreate], rules: SegmentationRules) -> list[CueCreate]:
    """Fold cues that are too brief to read into the next one."""
    if len(cues) < 2:
        return cues

    merged: list[CueCreate] = []
    pending: CueCreate | None = None

    for cue in cues:
        if pending is not None:
            combined = f"{pending.text} {cue.text}".strip()
            if len(combined) <= rules.max_chars:
                cue = CueCreate(start=pending.start, end=cue.end, text=combined)
            else:
                merged.append(pending)
            pending = None

        if (cue.end - cue.start) < rules.merge_below and len(cue.text) < rules.target_chars:
            pending = cue
            continue
        merged.append(cue)

    if pending is not None:
        merged.append(pending)
    return merged


def _enforce_timing(cues: list[CueCreate], rules: SegmentationRules) -> list[CueCreate]:
    """Apply minimum/maximum duration, reading speed and overlap rules."""
    result: list[CueCreate] = []
    previous_end = 0.0

    for cue in cues:
        start = max(cue.start, previous_end + rules.gap if result else cue.start)
        end = max(cue.end, start + rules.min_duration)

        # Give dense text enough time to be read.
        needed = len(cue.text) / rules.max_chars_per_second
        if end - start < needed:
            end = start + needed

        end = min(end, start + rules.max_duration)

        result.append(CueCreate(start=round(start, 3), end=round(end, 3), text=cue.text))
        previous_end = end

    return result


def _normalise(text: str) -> str:
    """Collapse whitespace without touching Persian joining characters."""
    return re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _strip_spaces(text: str) -> str:
    return re.sub(r"\s+", "", text)
