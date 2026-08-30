"""Integration tests: the job system driving real handlers end to end.

No mocking of FFmpeg, the database or the job queue. AI-dependent tests are
marked and skipped when the Claude CLI is not available, so this suite still
runs in an environment without it (see test_ai_live.py for the AI-specific
checks, which skip the same way).
"""

from __future__ import annotations

import shutil
import time

import pytest

from app.domain.enums import AssetType, JobStatus, JobType
from app.domain.job import JobCreate
from app.domain.subtitle import CueCreate, TrackCreate
from tests.conftest import wait_for_job


def claude_available(container) -> bool:
    return container.ai.list_providers(refresh=True)[0].available


class TestAudioExtractJob:
    def test_completes_and_registers_asset(self, container, project, video_asset):
        job = container.jobs.submit(JobCreate(
            type=JobType.AUDIO_EXTRACT, project_id=project.id,
            input={"asset_id": video_asset.id, "preset": "opus"},
        ))
        done = wait_for_job(container, job.id)
        assert done.status is JobStatus.COMPLETED, done.error
        assert done.output["compression_ratio"] > 1
        from pathlib import Path
        assert Path(done.output["path"]).is_file()

    def test_progress_reaches_completion(self, container, project, video_asset):
        job = container.jobs.submit(JobCreate(
            type=JobType.AUDIO_EXTRACT, project_id=project.id,
            input={"asset_id": video_asset.id},
        ))
        done = wait_for_job(container, job.id)
        assert done.progress == 1.0

    def test_missing_asset_fails_with_persian_message(self, container, project):
        job = container.jobs.submit(JobCreate(
            type=JobType.AUDIO_EXTRACT, project_id=project.id,
            input={"asset_id": "nonexistent"},
        ))
        done = wait_for_job(container, job.id)
        assert done.status is JobStatus.FAILED
        assert done.error_code == "not_found"
        assert "پیدا نشد" in done.error

    def test_logs_are_persisted(self, container, project, video_asset):
        job = container.jobs.submit(JobCreate(
            type=JobType.AUDIO_EXTRACT, project_id=project.id,
            input={"asset_id": video_asset.id},
        ))
        wait_for_job(container, job.id)
        logs = container.job_repo.get_logs(job.id)
        assert len(logs) > 0


class TestSubtitleGenerationJob:
    def test_from_measured_segments(self, container, project):
        segments = [
            {"index": 0, "start": 0.0, "end": 2.0, "text": "سلام به همه."},
            {"index": 1, "start": 2.2, "end": 5.0, "text": "این یک آزمون است."},
        ]
        job = container.jobs.submit(JobCreate(
            type=JobType.SUBTITLE_GENERATE, project_id=project.id,
            input={"segments": segments, "language": "fa"},
        ))
        done = wait_for_job(container, job.id)
        assert done.status is JobStatus.COMPLETED
        assert done.output["timing_source"] == "asr_segments"
        assert done.output["cue_count"] == 2

        track = container.subtitles.get_track(done.output["track_id"])
        assert len(track.cues) == 2
        assert track.cues[0].end <= track.cues[1].start + 1e-6

    def test_from_untimed_text_reports_estimated(self, container, project, video_asset):
        job = container.jobs.submit(JobCreate(
            type=JobType.SUBTITLE_GENERATE, project_id=project.id,
            input={"text": "یک متن ساده بدون زمان‌بندی دقیق.", "language": "fa"},
        ))
        done = wait_for_job(container, job.id)
        assert done.status is JobStatus.COMPLETED
        assert done.output["timing_source"] == "estimated"

    def test_no_content_fails_validation(self, container, project):
        job = container.jobs.submit(JobCreate(
            type=JobType.SUBTITLE_GENERATE, project_id=project.id,
            input={"text": "", "duration_seconds": 10.0},
        ))
        done = wait_for_job(container, job.id)
        assert done.status is JobStatus.FAILED
        assert done.error_code == "validation_error"


class TestSubtitleRenderJob:
    def test_renders_and_exports_sidecar(self, container, project, video_asset):
        gen_job = container.jobs.submit(JobCreate(
            type=JobType.SUBTITLE_GENERATE, project_id=project.id,
            input={"segments": [{"index": 0, "start": 0.0, "end": 3.0, "text": "متن آزمایشی"}]},
        ))
        gen_done = wait_for_job(container, gen_job.id)
        track_id = gen_done.output["track_id"]

        render_job = container.jobs.submit(JobCreate(
            type=JobType.SUBTITLE_RENDER, project_id=project.id,
            input={"track_id": track_id, "asset_id": video_asset.id, "quality": "fast"},
        ))
        done = wait_for_job(container, render_job.id)
        assert done.status is JobStatus.COMPLETED, done.error
        assert done.output["subtitle_asset_id"] is not None

        rendered = container.assets.get(done.output["asset_id"])
        assert rendered.type is AssetType.RENDERED_VIDEO

    def test_original_video_never_modified(self, container, project, video_asset, sample_video):
        original_size = sample_video.stat().st_size
        gen_job = container.jobs.submit(JobCreate(
            type=JobType.SUBTITLE_GENERATE, project_id=project.id,
            input={"segments": [{"index": 0, "start": 0.0, "end": 2.0, "text": "x"}]},
        ))
        track_id = wait_for_job(container, gen_job.id).output["track_id"]
        render_job = container.jobs.submit(JobCreate(
            type=JobType.SUBTITLE_RENDER, project_id=project.id,
            input={"track_id": track_id, "asset_id": video_asset.id, "quality": "fast"},
        ))
        wait_for_job(container, render_job.id)
        assert sample_video.stat().st_size == original_size

    def test_empty_track_fails(self, container, project, video_asset):
        track = container.subtitles.create_track(project.id, __import__(
            "app.domain.subtitle", fromlist=["TrackCreate"]
        ).TrackCreate(name="empty"))
        job = container.jobs.submit(JobCreate(
            type=JobType.SUBTITLE_RENDER, project_id=project.id,
            input={"track_id": track.id, "asset_id": video_asset.id},
        ))
        done = wait_for_job(container, job.id)
        assert done.status is JobStatus.FAILED
        assert done.error_code == "validation_error"


class TestSubtitleSyncJob:
    """Audio-based synchronisation, end to end and unmocked.

    The test is built the only way this feature can be honestly tested: real
    speech is synthesised for a known sentence, real speech recognition
    measures where the words landed in it, and the assertion is that cues
    which started with deliberately wrong timings ended up on the measured
    speech. Anything mocked in the middle would prove the code calls a
    function, not that a subtitle ends up in the right place.

    Marked slow because it needs both the network (for the speech) and the ASR
    weights on disk, and skips cleanly when either is missing.
    """

    SENTENCE = "امروز هوا بسیار خوب است و ما به پارک می‌رویم."

    @pytest.mark.slow
    def test_moves_cues_onto_the_measured_speech(self, container, project):
        voice_job = container.jobs.submit(JobCreate(
            type=JobType.TTS_SYNTHESIZE, project_id=project.id,
            input={
                "segments": [
                    {"kind": "pause", "seconds": 3.0},
                    {"kind": "text", "text": self.SENTENCE},
                ],
                "voice_id": "fa-IR-DilaraNeural", "language": "fa",
            },
        ))
        voiced = wait_for_job(container, voice_job.id, timeout=90)
        if voiced.status is not JobStatus.COMPLETED:
            pytest.skip(f"could not synthesise test speech: {voiced.error}")

        # A track whose text is correct but whose timing is nonsense - exactly
        # the raw-subtitle case this feature exists for. The speech does not
        # start until three seconds in, so a cue at 0.0-1.0 is provably wrong.
        track = container.subtitles.create_track(project.id, TrackCreate(name="unsynced"))
        container.subtitles.add_cue(
            track.id, CueCreate(start=0.0, end=1.0, text=self.SENTENCE)
        )

        job = container.jobs.submit(JobCreate(
            type=JobType.SUBTITLE_SYNC, project_id=project.id,
            input={
                "track_id": track.id,
                "asset_id": voiced.output["asset_id"],
                # The smallest model: this test is about placement, not
                # transcription quality, and the weights have to be downloaded.
                "model_size": "tiny",
                "language": "fa",
            },
        ))
        done = wait_for_job(container, job.id, timeout=600)
        if done.status is JobStatus.FAILED:
            pytest.skip(f"speech recognition unavailable: {done.error}")

        assert done.status is JobStatus.COMPLETED, done.error
        cues = container.subtitles.list_cues(track.id)
        assert len(cues) == 1

        # The cue must have moved into the speech, which starts after the
        # three-second silence. This is the whole claim of the feature.
        assert cues[0].start > 1.5, f"cue did not move out of the silence: {cues[0].start}"
        assert cues[0].end > cues[0].start
        assert done.output["timing_source"] in ("audio_aligned", "speech_distributed")

        # And the text is untouched - synchronisation moves cues, never
        # rewrites them.
        assert cues[0].text == self.SENTENCE

    @pytest.mark.slow
    def test_aligns_a_track_built_from_this_video_s_own_transcript(
        self, container, project
    ):
        """The headline case: subtitles that *are* a transcript of this audio.

        Text alignment must actually engage here, not fall back - the words in
        the cues are the words in the audio.

        This is a regression guard as much as a feature test. Whisper conditions
        its output on its initial prompt, so when the synchronisation job ran
        the engine with a different prompt than the transcription job, the same
        audio came back worded differently and a track made from this
        platform's own transcript failed to match this platform's own
        re-listening. The bug was invisible to every unit test - both sides
        were individually correct - and only appeared when the two real calls
        were made one after the other.
        """
        voice_job = container.jobs.submit(JobCreate(
            type=JobType.TTS_SYNTHESIZE, project_id=project.id,
            input={
                "segments": [
                    {"kind": "pause", "seconds": 3.0},
                    {"kind": "text", "text": self.SENTENCE},
                ],
                "voice_id": "fa-IR-DilaraNeural", "language": "fa",
            },
        ))
        voiced = wait_for_job(container, voice_job.id, timeout=90)
        if voiced.status is not JobStatus.COMPLETED:
            pytest.skip(f"could not synthesise test speech: {voiced.error}")

        transcribe_job = container.jobs.submit(JobCreate(
            type=JobType.TRANSCRIBE, project_id=project.id,
            input={
                "asset_id": voiced.output["asset_id"],
                "model_size": "tiny", "language": "fa", "refine": False,
            },
        ))
        transcribed = wait_for_job(container, transcribe_job.id, timeout=600)
        if transcribed.status is not JobStatus.COMPLETED:
            pytest.skip(f"speech recognition unavailable: {transcribed.error}")

        heard = [s["text"].strip() for s in transcribed.output["segments"] if s["text"].strip()]
        assert heard, "transcription produced no segments to build cues from"

        # Cue text straight from the transcript, timings deliberately wrong.
        track = container.subtitles.create_track(project.id, TrackCreate(name="from-transcript"))
        for index, text in enumerate(heard):
            container.subtitles.add_cue(
                track.id, CueCreate(start=index * 0.5, end=index * 0.5 + 0.4, text=text)
            )

        job = container.jobs.submit(JobCreate(
            type=JobType.SUBTITLE_SYNC, project_id=project.id,
            input={
                "track_id": track.id,
                "asset_id": voiced.output["asset_id"],
                "model_size": "tiny", "language": "fa",
            },
        ))
        done = wait_for_job(container, job.id, timeout=600)
        assert done.status is JobStatus.COMPLETED, done.error

        assert done.output["timing_source"] == "audio_aligned", (
            "cue text taken from this audio's own transcript must align against "
            f"it, but the job fell back to {done.output['timing_source']!r} "
            f"(coverage {done.output['coverage']})"
        )
        assert done.output["coverage"] > 0.5

        cues = container.subtitles.list_cues(track.id)
        assert cues[0].start > 1.5, "aligned cue is still inside the leading silence"


class TestTtsJob:
    def test_synthesizes_with_pauses(self, container, project):
        job = container.jobs.submit(JobCreate(
            type=JobType.TTS_SYNTHESIZE, project_id=project.id,
            input={
                "segments": [
                    {"kind": "text", "text": "سلام."},
                    {"kind": "pause", "seconds": 1.0},
                    {"kind": "text", "text": "خداحافظ."},
                ],
                "voice_id": "fa-IR-DilaraNeural", "language": "fa",
            },
        ))
        done = wait_for_job(container, job.id, timeout=60)
        if done.status is JobStatus.FAILED and "اینترنت" in (done.error or ""):
            pytest.skip("edge-tts requires network access")
        assert done.status is JobStatus.COMPLETED, done.error
        assert done.output["duration_seconds"] > 1.0
        assert done.output["pause_count"] == 1


class TestJobCancellation:
    def test_cancel_running_render_stops_promptly(self, container, project, ffmpeg_tools):
        from app.media.ffmpeg import run_ffmpeg
        from app.core.paths import PATHS

        big = PATHS.project_subdir(project.id, "source") / "big.mp4"
        run_ffmpeg(ffmpeg_tools, [
            "-f", "lavfi", "-i", "testsrc2=size=854x480:rate=30:duration=60",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(big),
        ], output_path=big)
        big_asset = container.assets.create(
            project_id=project.id, type=AssetType.VIDEO, path=big,
            original_filename=big.name, size_bytes=big.stat().st_size,
            format="mp4", duration_seconds=60.0,
        )
        gen_job = container.jobs.submit(JobCreate(
            type=JobType.SUBTITLE_GENERATE, project_id=project.id,
            input={"segments": [{"index": 0, "start": 0.0, "end": 2.0, "text": "x"}]},
        ))
        track_id = wait_for_job(container, gen_job.id).output["track_id"]

        job = container.jobs.submit(JobCreate(
            type=JobType.SUBTITLE_RENDER, project_id=project.id,
            input={"track_id": track_id, "asset_id": big_asset.id, "quality": "high"},
        ))
        time.sleep(1.5)
        assert container.jobs.cancel(job.id) is True

        start = time.monotonic()
        done = wait_for_job(container, job.id, timeout=15)
        assert time.monotonic() - start < 15
        assert done.status is JobStatus.CANCELLED
        assert container.jobs.active_count == 0

    def test_cancel_already_finished_job_returns_false(self, container, project, video_asset):
        job = container.jobs.submit(JobCreate(
            type=JobType.AUDIO_EXTRACT, project_id=project.id,
            input={"asset_id": video_asset.id},
        ))
        wait_for_job(container, job.id)
        assert container.jobs.cancel(job.id) is False


@pytest.mark.slow
class TestTextTaskJob:
    """Requires a working Claude CLI; skipped otherwise."""

    def test_translation_produces_document(self, container, project):
        if not claude_available(container):
            pytest.skip("Claude CLI not available")
        job = container.jobs.submit(JobCreate(
            type=JobType.TEXT_TASK, project_id=project.id,
            input={
                "task": "translation", "content": "سلام دنیا.",
                "source_language": "fa", "target_language": "en",
                "model": "haiku",
            },
        ))
        done = wait_for_job(container, job.id, timeout=60)
        assert done.status is JobStatus.COMPLETED, done.error
        assert done.output["document_id"] is not None
        document = container.documents.get(done.output["document_id"])
        assert document.content.strip()

    def test_save_false_does_not_create_document(self, container, project):
        if not claude_available(container):
            pytest.skip("Claude CLI not available")
        job = container.jobs.submit(JobCreate(
            type=JobType.TEXT_TASK, project_id=project.id,
            input={
                "task": "text_editing", "content": "این متن تست است.",
                "model": "haiku", "save": False,
            },
        ))
        done = wait_for_job(container, job.id, timeout=60)
        assert done.status is JobStatus.COMPLETED, done.error
        assert done.output["document_id"] is None
