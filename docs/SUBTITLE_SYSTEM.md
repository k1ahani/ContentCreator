# Subtitle System (Feature 5)

## Purpose

How subtitles are represented, generated, styled, edited, and serialised.
This is the most structurally important feature in the platform — the
requirement is explicit that subtitles must never be "one giant text field,"
and this document explains how that's enforced end to end, backend through
frontend. Read `docs/VIDEO_RENDERING.md` for how a track becomes a burned-in
video.

## Data model

```
SubtitleTrack
├── id, project_id, name, language
├── style: SubtitleStyle          one style per track (not per cue, by default)
├── source_document_id            the transcript this was generated from, if any
└── cues: list[SubtitleCue]
        ├── id, track_id, index    index = explicit position, not implied by time
        ├── start, end              float seconds
        ├── text
        └── style_overrides         per-cue overrides on top of the track style
```

`app/domain/subtitle.py`. Cues are never a blob of text — every cue is its own
row with its own timing, from the database (`subtitle_cues` table) up through
the domain model to the frontend's timeline component.

**Why `index` is explicit rather than derived by sorting on `start`.** During
a drag in the timeline editor, a cue's time changes before the operation
settles; if ordering were implied by `start`, cues could visually reorder
themselves mid-drag as the dragged cue's time crosses a neighbour's. The
`idx` column (`app/db/repositories/subtitles.py`) is maintained explicitly and
only renumbered by `reindex()` after a structural change (split, merge,
insert-at-position) — never implicitly during an edit.

## Generation: from transcript to cues

`app/media/subtitles/segmentation.py`. Two paths, and the distinction matters:

**Timed segments** (the normal path, `cues_from_segments`) — input is
`TranscriptSegment` objects with real timings measured from the audio by the
ASR engine (`app/transcription/`). When a segment is too long for one cue, it
splits using **word-level timings** when the engine provided them
(`_split_by_words`), falling back to proportional splitting by character count
within the segment's own time span only when word timings aren't available.
Either way, split timings are real or a close approximation of real — never
invented from nothing.

**Untimed text** (`cues_from_text`) — no measured timings exist at all (e.g.
subtitles from a hand-written document), so time is distributed across cues by
character-count proportion of a known total duration. This is honest about
being approximate: the job handler
(`app/jobs/handlers/subtitle_generate.py`) reports `timing_source: "estimated"`
in its output specifically so the frontend can flag it — a real distinction
the UI surfaces, not swept under the rug.

**Readability rules** (`SegmentationRules`, standard broadcast-subtitle
practice): max 84 characters per cue, minimum 1.0s / maximum 7.0s duration,
maximum ~21 characters/second reading speed (dense text gets its duration
extended to stay readable), and a small gap enforced between consecutive cues.
Splitting prefers a sentence boundary, then a clause boundary (Persian و Latin
punctuation both recognised), then a word boundary — **never mid-word**, in
either script. This character-length cascade is what `AUTOMATIC` mode below
uses; the other four modes bypass it.

### Segmentation mode

`SubtitleSegmentationMode` (`app/domain/enums.py`) chooses *how* cue
boundaries are picked, independent of the timed-vs-untimed distinction above —
it applies equally to `cues_from_segments` and `cues_from_text`. Selected per
generation request (`GenerateSubtitleRequest.segmentation_mode`, plumbed
through `_rules_from_settings` in `app/jobs/handlers/subtitle_generate.py`);
omitted, it defaults to `AUTOMATIC`.

| Mode | Behaviour |
| --- | --- |
| `sentence` | One cue per complete sentence (`_split_on(text, _SENTENCE_END)`), never split further regardless of length. |
| `automatic` | The character-length cascade described above — the original, and still the default. |
| `short` | Fixed 3 words per cue. |
| `normal` | Fixed 6 words per cue. |
| `custom` | Fixed `words_per_cue` (1–20, from the request) words per cue — e.g. one word per cue for a karaoke-style track. |

`short`/`normal`/`custom` all go through `_split_by_word_count`, which packs
exactly N words per chunk (`words[i:i+n]`) and never breaks a word. A mode-aware
`_needs_split` decides whether a segment needs splitting at all, replacing the
old hardcoded character/duration check.

**Why `_merge_tiny` (which recombines cues that end up implausibly short) only
runs for `AUTOMATIC`.** For every other mode, a "too short" cue is exactly
what the user asked for — silently re-merging a sentence-mode cue or a
one-word `custom` cue back together would defeat the whole point of choosing
that mode.

## Synchronisation: fixing a track whose text is already right

`app/media/subtitles/sync.py`. Segmentation decides *what text goes in a cue*;
this module decides *when an existing cue appears*. It exists for the case the
generation path cannot serve: a subtitle file that arrived with the video (or
was pasted in as a document) whose words are correct and whose timings are
`estimated` — distributed by character count across the whole file, drifting
further from the speech with every minute.

There are deliberately **two** methods, because they answer different questions
and the user knows which one they need before the platform does.

### 1. Automatic, from the video's audio

`JobType.SUBTITLE_SYNC` (`app/jobs/handlers/subtitle_sync.py`),
`POST /api/projects/{id}/subtitles/sync`. Re-extracts the audio into `temp/`
(WAV, deleted afterwards — the source video is never touched), runs the same
speech-recognition layer transcription uses, and moves the existing cues onto
the measured word timings. Two placement strategies, and which one ran is
always reported in `timing_source`:

- **`audio_aligned`** — cue text matched against the ASR word stream with
  `difflib.SequenceMatcher`. Matched cues take the *real measured times* of the
  words they matched; unmatched cues are interpolated between their matched
  neighbours by character count. Tolerates mis-heard, dropped and inserted
  words, which a positional zip could not — that would desynchronise
  permanently at the engine's first mistake.
- **`speech_distributed`** — the fallback when coverage falls below
  `MIN_ALIGNMENT_COVERAGE` (0.35). Cue text is distributed across the *measured
  speech regions* rather than the file's whole duration, so silence, music and
  gaps between speakers no longer consume subtitle time. Still approximate, and
  reported as such. This is what a translated track gets, since its words can
  never match the audio.

**Both sides of a comparison must decode identically.** The sync handler seeds
Whisper with the same `DEFAULT_PERSIAN_SEED_PROMPT` the transcribe handler uses.
This is not tidiness: Whisper conditions its output on its initial prompt, so
running it with a different prompt returns *differently worded* text for
identical audio — and a track built from this platform's own transcript then
fails to match this platform's own re-listening, falling back to distribution
for no reason but an inconsistency between two of our own calls. This was a real
bug, invisible to unit tests (both calls were individually correct) and caught
only by running the two in sequence against real audio.

### 2. Manual / batch, from arithmetic

`POST /api/projects/{id}/subtitles/{track_id}/retime`. Answers **inline, not as
a job** — it reads no media and runs no external tool, so a progress bar would
be theatre. Four modes (`SubtitleRetimeMode`), each applying to every cue at
once so the user never drags fifty cues by hand:

| Mode | What it does | When |
| --- | --- | --- |
| `shift` | Adds a signed offset to every cue. | "Everything is 2s late." |
| `reading_speed` | Recomputes each cue's duration from *its own* text length at a target characters-per-second, then repacks the track end to end. | "Subtitles flick past too fast." |
| `scale` | Multiplies every timing around an anchor (the first cue's start). | Drift that grows through the file — a 25 vs 23.976 fps mismatch. |
| `stretch` | Scales so the last cue ends at a given time. | "Make the subtitles finish when the video does." |

`shift` clamps at zero rather than going negative, which means a large negative
shift *shortens* a cue already pressed against the start of the video instead of
moving it. Every other cue keeps its duration and spacing; this matches what
desktop subtitle editors do, and is documented on `_shift` because it surprises
people.

### The hygiene pass, and why every path ends in it

`sync.py::sanitize` runs after **every** retime mode and after **both**
placement strategies. It is not tidiness — each rule exists because of a
specific way a burned-in render goes wrong:

- **Overlaps** → libass draws every cue covering the current frame, so two
  overlapping cues are two stacked subtitle boxes. A naive "shift everything"
  produces one the moment two cues cross.
- **Sub-frame durations** → a cue whose end lands on or before its start
  violates the `end_seconds > start_seconds` CHECK on `subtitle_cues` and the
  write fails outright, so `min_duration` is a correctness floor, not taste.
- **Runaway durations** → a cue held for a minute reads as a frozen frame.
- **Overrunning the media** → clamped inside `media_duration` when it is known.

Where the media ceiling and cue ordering genuinely conflict (more cues than the
video has room for), **ordering wins**: a cue past the end of the video is
simply not drawn, while two cues stacked on one instant is a visible defect.

A `RetimeReport` accompanies every result — cues changed, overlaps fixed,
durations adjusted, cues clamped, largest shift — so the UI can state what
happened rather than saying "done".

### One more hygiene pass, at render time

`sync.py::prepare_for_render`, called from the render handler, catches the two
problems that only become visible once subtitles are actually burned in:

- **Blank cues are dropped.** An empty cue still emits a `Dialogue` line, and
  with the default style (`background_opacity > 0` → ASS `BorderStyle=3`, an
  opaque box) that line draws an **empty coloured box** over the picture for its
  whole duration.
- **Overlaps are resolved**, with a one-centisecond minimum gap — the resolution
  of an ASS timecode. A smaller gap rounds two cues onto the same boundary in
  the written script and libass stacks them again, re-creating at the last step
  the artefact that was resolved everywhere upstream.

Its rules are deliberately far looser than the retiming rules: a twenty-second
title card is intent, not a mistake, and a render must never silently re-time
what the user placed by hand in the timeline editor. The sidecar `.srt` written
alongside a render uses the same corrected cues, so the burned-in subtitles and
the exported file can never disagree about timing.

## Styling: one model drives two renderers

`app/domain/subtitle.py::SubtitleStyle` is the single source of truth for
appearance, and it drives **both** the browser preview and the actual burned-in
render — this is what makes the live preview trustworthy rather than
decorative:

- `app/media/subtitles/style.py::to_ass_style_line` → an ASS `Style:` line
  FFmpeg's `subtitles` filter (via libass) actually uses.
- `frontend/src/lib/subtitleStyle.ts::cueBoxStyle` → CSS for the live preview
  overlay on the HTML5 `<video>` element.

Two ASS details worth knowing before editing either side:

- **Colour format is `&HAABBGGRR`** — byte order reversed from CSS, and alpha
  is *inverted* (`00` = opaque, `FF` = transparent). See
  `style.py::hex_to_ass_colour`.
- **A visible background is `BorderStyle=3`** (opaque box), and in that mode
  libass fills the box using the *outline* colour slot, not `BackColour`. A
  style with `background_opacity > 0` is therefore emitted as `BorderStyle=3`
  with the background colour placed in the outline slot; a style with no
  background uses `BorderStyle=1` with a real outline and drop shadow instead.

If you change one side, change the other — `docs/VIDEO_RENDERING.md` explains
the canvas-size scaling that keeps the two visually consistent too.

## Formats: SRT / VTT / ASS

`app/media/subtitles/formats.py`. All three read and (for SRT) write
correctly, but they are not equivalent:

- **ASS is what actually gets burned in** — it's the only one of the three
  that carries styling FFmpeg can honour.
- **SRT/VTT are export-only** — for uploading alongside a video separately.
- **SRT is written with a UTF-8 BOM** (`utf-8-sig`) because many players guess
  the encoding of an SRT file wrongly without one, particularly for non-Latin
  text; **ASS is written without a BOM** because some libass builds mishandle
  one. This asymmetry is intentional, not an oversight.
- Cue text with a literal `{` or `}` is escaped (`\{`, `\}`) before writing
  ASS, because an unescaped brace opens an ASS override block and silently
  eats the rest of the line — a real regression class, covered by a Persian
  test case with braces and a backslash in
  `backend/tests/integration/test_media_pipeline.py`.

## The timeline editor (frontend)

`frontend/src/pages/project/SubtitleEditorPage.tsx` plus
`frontend/src/components/subtitle/{SubtitleTimeline,CueDetailPanel,StylePanel,VideoPreview,SyncPanel}.tsx`.

- **Optimistic local state, debounced writes.** Cue edits update local state
  immediately (so dragging and typing feel instant) and are persisted per-cue
  with a ~400ms debounce (`commitCue` in `SubtitleEditorPage.tsx`). Split and
  merge go straight to the server instead, because they change the cue
  *count* — optimistic local arithmetic for those would drift from what the
  backend actually computed (renumbered indices, exact split point).
- **Drag interactions** (`SubtitleTimeline.tsx`): dragging a cue's body moves
  both start and end together; dragging an edge resizes just that boundary.
  The timeline forces an LTR coordinate space internally (`dir="ltr"` wrapper)
  regardless of the page's RTL direction — time conventionally increases
  left-to-right on a scrubber regardless of UI language, and mixing that with
  RTL layout would make dragging feel backwards.
- **Synchronisation cancels pending writes.** Both sync paths write straight to
  the database, so the page's in-flight debounced per-cue writes are cleared
  before the new cues are adopted (`onCuesChanged` in `SubtitleEditorPage.tsx`).
  Without that, a write still inside its 400ms window would land afterwards and
  snap a just-synchronised cue back to its old time.
- **Click-to-seek and click-to-select** share one handler
  (`handleTrackClick`), distinguishing "clicked empty timeline" (seek the
  video, deselect) from "clicked a cue block" (`data-cue-block` guard) so
  the two gestures never fight each other.

## Adding a subtitle format

Add a serialiser function to `app/media/subtitles/formats.py` following the
`to_srt`/`to_vtt`/`to_ass` pattern, wire it into `write_subtitle_file`'s
suffix dispatch, and add the format to the `SubtitleFormat` enum
(`app/domain/enums.py`). The export endpoint
(`POST /api/projects/{id}/subtitles/{track}/export`) and the frontend's format
buttons pick it up automatically once it's in the enum.

## Common mistakes

- **Treating cues as sortable-by-time instead of index-ordered.** Always
  respect `idx` for display order; only re-derive it via `reindex()` after a
  structural change.
- **Styling only one of the two renderers.** A style field that only affects
  the ASS output (or only the CSS preview) breaks the "preview is
  trustworthy" guarantee — always update both `style.py` and
  `subtitleStyle.ts` together.
- **Assuming generation always has real timings.** Check `timing_source` in
  the generation job's output before treating a track's timing as
  authoritative.
- **Writing cue timings without sanitising them.** Every path that sets timings
  goes through `sync.py::sanitize` (or `prepare_for_render` at render time). An
  unsanitised write is what produces stacked subtitles and failed inserts.
- **Rewriting cue text during synchronisation.** Synchronisation moves cues; it
  never changes a character of what they say. `SubtitleRepository.retime_cues`
  updates only `start_seconds`/`end_seconds` — deliberately not `replace_cues`,
  which would discard cue ids (breaking the editor's selection) and any per-cue
  style overrides.

## Testing

`backend/tests/unit/test_subtitles.py` covers timecode round-tripping, ASS
colour/alignment math, format serialisation (including the brace-escaping
and BOM behaviour), and segmentation (word-boundary splitting, overlap
prevention, reading-speed enforcement) without touching FFmpeg.
`backend/tests/unit/test_subtitle_sync.py` covers re-timing: all four batch
modes, word alignment (mis-heard words, interpolation of unmatched cues,
Persian orthographic folding, and refusing to align a translated track), speech
distribution, and the render hygiene pass. Its `assert_renderable` helper
states the no-overlap/positive-duration invariants once, and every mode is
checked against it.

`backend/tests/integration/test_jobs_pipeline.py::TestSubtitleGenerationJob`
and `TestSubtitleRenderJob` exercise the full job pipeline, including the
`estimated` vs `asr_segments` timing-source distinction. `TestSubtitleSyncJob`
synthesises real speech, runs real speech recognition over it, and asserts that
cues with deliberately wrong timings land on the measured audio — nothing
mocked in between. Its second test builds the cues from the video's *own*
transcript and requires `timing_source == "audio_aligned"`, which is the
regression guard for the initial-prompt consistency described above.
