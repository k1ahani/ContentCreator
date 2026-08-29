"""Integration tests: real FFmpeg, real files, no mocking.

These are the tests that catch what unit tests cannot - a wrong FFmpeg flag, a
filtergraph escaping bug, a codec that cannot be copied into MP4. Every
assertion here is checked against bytes actually produced by FFmpeg.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.media.audio import extract_audio
from app.media.ffmpeg import probe_media, run_ffmpeg
from app.media.video import render_subtitles
from app.domain.subtitle import SubtitleCue, SubtitleStyle

pytestmark = pytest.mark.usefixtures("ffmpeg_tools")


def make_cue(start, end, text, index=0) -> SubtitleCue:
    return SubtitleCue(id=f"c{index}", track_id="t", index=index, start=start, end=end, text=text)


class TestAudioExtraction:
    def test_produces_mono_track(self, ffmpeg_tools, sample_video, tmp_path):
        result = extract_audio(
            ffmpeg_tools, source=sample_video, output_dir=tmp_path, preset_id="mp3"
        )
        probe = probe_media(ffmpeg_tools, result.output_path)
        assert probe.channels == 1

    def test_source_video_untouched(self, ffmpeg_tools, sample_video, tmp_path):
        original_size = sample_video.stat().st_size
        extract_audio(ffmpeg_tools, source=sample_video, output_dir=tmp_path, preset_id="opus")
        assert sample_video.stat().st_size == original_size

    def test_output_is_smaller_than_source(self, ffmpeg_tools, sample_video, tmp_path):
        result = extract_audio(
            ffmpeg_tools, source=sample_video, output_dir=tmp_path, preset_id="opus"
        )
        assert result.output_size_bytes < result.input_size_bytes

    @pytest.mark.parametrize("preset", ["opus", "mp3", "wav"])
    def test_every_preset_produces_playable_audio(
        self, ffmpeg_tools, sample_video, tmp_path, preset
    ):
        result = extract_audio(
            ffmpeg_tools, source=sample_video, output_dir=tmp_path / preset, preset_id=preset
        )
        probe = probe_media(ffmpeg_tools, result.output_path)
        assert probe.has_audio
        assert probe.duration_seconds == pytest.approx(4.0, abs=0.3)

    def test_progress_callback_fires(self, ffmpeg_tools, sample_video, tmp_path):
        updates = []
        extract_audio(
            ffmpeg_tools, source=sample_video, output_dir=tmp_path, preset_id="opus",
            on_progress=lambda f, s: updates.append(f),
        )
        assert len(updates) > 0

    def test_persian_filename_source_and_output(self, ffmpeg_tools, tmp_path):
        persian_dir = tmp_path / "پروژه"
        persian_dir.mkdir()
        source = persian_dir / "ویدیوی من.mp4"
        run_ffmpeg(
            ffmpeg_tools,
            ["-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=2",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(source)],
            output_path=source,
        )
        result = extract_audio(
            ffmpeg_tools, source=source, output_dir=persian_dir, preset_id="opus"
        )
        assert result.output_path.is_file()

    def test_never_overwrites_existing_output(self, ffmpeg_tools, sample_video, tmp_path):
        first = extract_audio(
            ffmpeg_tools, source=sample_video, output_dir=tmp_path, preset_id="opus"
        )
        second = extract_audio(
            ffmpeg_tools, source=sample_video, output_dir=tmp_path, preset_id="opus"
        )
        assert first.output_path != second.output_path
        assert first.output_path.is_file() and second.output_path.is_file()


class TestSubtitleRendering:
    def test_burns_subtitles_into_video(self, ffmpeg_tools, sample_video, tmp_path):
        cues = [make_cue(0.5, 2.5, "سلام دنیا")]
        result = render_subtitles(
            ffmpeg_tools, source=sample_video, cues=cues, style=SubtitleStyle(),
            output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp", quality_id="fast",
        )
        assert result.output_path.is_file()
        assert result.output_size_bytes > 0

    def test_source_video_untouched_by_render(self, ffmpeg_tools, sample_video, tmp_path):
        original_size = sample_video.stat().st_size
        render_subtitles(
            ffmpeg_tools, source=sample_video, cues=[make_cue(0.0, 1.0, "x")],
            style=SubtitleStyle(), output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp",
        )
        assert sample_video.stat().st_size == original_size

    def test_rendered_frame_differs_from_source(self, ffmpeg_tools, sample_video, tmp_path):
        """The definitive proof subtitles were actually burned in, not just
        that ffmpeg exited 0."""
        result = render_subtitles(
            ffmpeg_tools, source=sample_video, cues=[make_cue(0.5, 3.5, "متن آزمایشی")],
            style=SubtitleStyle(), output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp",
            quality_id="fast",
        )
        frame_src = tmp_path / "src.png"
        frame_out = tmp_path / "out.png"
        run_ffmpeg(ffmpeg_tools, ["-ss", "1.0", "-i", str(sample_video),
                                   "-frames:v", "1", str(frame_src)], output_path=frame_src)
        run_ffmpeg(ffmpeg_tools, ["-ss", "1.0", "-i", str(result.output_path),
                                   "-frames:v", "1", str(frame_out)], output_path=frame_out)
        assert frame_src.read_bytes() != frame_out.read_bytes()

    def test_temp_ass_files_are_cleaned_up(self, ffmpeg_tools, sample_video, tmp_path):
        temp_dir = tmp_path / "tmp"
        render_subtitles(
            ffmpeg_tools, source=sample_video, cues=[make_cue(0.0, 1.0, "x")],
            style=SubtitleStyle(), output_dir=tmp_path / "out", temp_dir=temp_dir,
        )
        assert list(temp_dir.glob("*.ass")) == []

    def test_persian_text_survives_render(self, ffmpeg_tools, sample_video, tmp_path):
        """A regression guard for ASS brace/backslash escaping with Persian text."""
        cues = [make_cue(0.0, 2.0, "سلام {دنیا} با بک‌اسلش \\ و کاما، اینجا")]
        result = render_subtitles(
            ffmpeg_tools, source=sample_video, cues=cues, style=SubtitleStyle(),
            output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp", quality_id="fast",
        )
        assert result.output_path.is_file()
        probe = probe_media(ffmpeg_tools, result.output_path)
        assert probe.has_video

    def test_rejects_empty_cue_list(self, ffmpeg_tools, sample_video, tmp_path):
        from app.core.errors import MediaError

        with pytest.raises(MediaError):
            render_subtitles(
                ffmpeg_tools, source=sample_video, cues=[], style=SubtitleStyle(),
                output_dir=tmp_path / "out", temp_dir=tmp_path / "tmp",
            )
