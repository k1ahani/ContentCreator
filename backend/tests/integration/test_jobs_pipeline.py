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
