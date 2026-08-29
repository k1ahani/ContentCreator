# Video Rendering (Feature 5: Subtitle Burn-In)

## Purpose

`app/media/video.py::render_subtitles` — burn a subtitle track into a new
MP4. Read `docs/MEDIA_PROCESSING.md` for the shared FFmpeg plumbing and
`docs/SUBTITLE_SYSTEM.md` for how cues and styles are represented before they
reach this module.

## The Windows path-escaping problem, and how it's avoided

This is the trickiest part of this module and the thing most likely to break
if touched carelessly.

FFmpeg's `subtitles` filter takes its file argument inside a **filtergraph
string**, where FFmpeg's own mini-language treats `:` as an option separator,
`,` as a filter separator, and `\` as an escape character. A real Windows path
like `E:\LoyalAxis\ContentCreatorApp\storage\projects\<id>\temp\track.ass` is a
minefield under those rules — the drive-letter colon alone breaks naive
escaping, and a Persian project or file name compounds it further.

**The fix sidesteps the problem entirely rather than solving the escaping.**
`render_subtitles`:

1. Writes the ASS script to a short, ASCII-only, randomly-named file
   (`sub_<id>.ass`) inside a temp directory.
2. Runs FFmpeg **with that temp directory as its working directory**
   (`run_ffmpeg(..., cwd=temp_dir)`).
3. References the subtitle file in the filtergraph by its **bare filename**:
   `subtitles=filename=sub_xxxx.ass` — no drive letter, no backslashes, no
   Persian characters anywhere in the filtergraph string.

**If you ever see `subtitles=filename=` built with an absolute path or
anything containing a colon, that's a regression** — it will work on some
inputs and mysteriously fail on others (anything with `:` in the resolved
path, which is every Windows absolute path).

Fonts follow the same pattern: if `bin/fonts/` has files in it, they're copied
next to the script and referenced as `:fontsdir=fonts` (relative), not an
absolute path.

## Authoring canvas matches the real video

The ASS script is authored against the source video's actual resolution
(`play_res_x=probe.width or 1920`, `play_res_y=probe.height or 1080`), not a
fixed canvas. This is why the frontend preview
(`frontend/src/lib/subtitleStyle.ts`) scales font size by
`videoElement.getBoundingClientRect().width / videoElement.videoWidth` — using
the video's own native resolution as the reference, matching exactly what the
backend uses as `PlayResX`. If the backend's canvas logic changes, the
frontend scaling calculation must change with it, or the preview and the
render will disagree on how big text looks.

## Audio handling

`-c:a copy` by default — the audio stream is never re-encoded, since burning
in subtitles has nothing to do with audio and re-encoding would only lose
quality for no reason. `_run_with_audio_fallback` catches the one real failure
mode this creates: a source codec that copy-compatible with the source
container but **not legal inside MP4** (Vorbis or Opus from a WebM source,
for instance). On that specific failure it retries once with `-c:a aac -b:a
192k`. Do not broaden this retry to swallow other FFmpeg errors — it matches
on specific stderr substrings (`could not find tag for codec`,
`incompatible with output`, `codec not currently supported in container`) so
a genuinely broken input still surfaces its real error.

## Quality presets

| id | crf | preset | trade-off |
|---|---|---|---|
| `high` | 18 | slow | best quality, largest file, slowest |
| `balanced` (default) | 21 | medium | |
| `fast` | 24 | veryfast | quickest turnaround, smallest quality loss cost |

## Guarantees

- **The source video is never modified.** Output is always a fresh
  `<stem>-subtitled.mp4` via `unique_path` in `storage/projects/<id>/rendered/`.
- **The temporary `.ass` file is always cleaned up**, including on failure
  (`finally: ass_path.unlink(missing_ok=True)`).
- **An empty cue list is rejected before FFmpeg runs** — there is nothing
  meaningful to render, and running FFmpeg anyway would produce a copy with no
  actual subtitles, silently pretending to succeed.

## Flow

`app/jobs/handlers/subtitle_render.py` (`JobType.SUBTITLE_RENDER`):

1. Load the track and its cues; reject if empty.
2. Probe the source video (needs `has_video`).
3. Call `render_subtitles`, streaming progress/log into the job console.
4. Register the rendered file as a `media_assets` row of type
   `rendered_video`.
5. Optionally also export a sidecar subtitle file (`.srt` by default, per the
   `subtitle.export_format` setting) — free to produce now that the cues are
   already resolved, useful for uploading alongside the video separately.

## Common mistakes

- **Passing an absolute or Persian-containing path into the `subtitles`
  filter.** See the escaping section above — always go through the
  relative-filename-plus-cwd pattern.
- **Re-encoding audio unconditionally.** Only do it on the specific fallback
  path; the default must stay `-c:a copy`.
- **Rendering with a canvas size that doesn't match the source.** Always pass
  `probe.width`/`probe.height` as `play_res_x`/`play_res_y`, or the frontend
  preview and the actual render will show different relative font sizes.

## Testing

`backend/tests/integration/test_media_pipeline.py::TestSubtitleRendering`
proves the burn-in actually happened, not just that FFmpeg exited 0: it
extracts the same frame from source and output and asserts the bytes differ.
It also covers Persian text with braces and backslashes (a regression guard
for `app/media/subtitles/formats.py::_escape_ass_text`) and confirms the
temporary `.ass` file is removed afterward.
