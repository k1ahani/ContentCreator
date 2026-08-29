"""Integration tests for the HTTP API using a real TestClient.

Exercises routers against the real container fixture - real database, real
FFmpeg where relevant - so a serialisation mismatch between a domain model and
its Pydantic response schema is caught here rather than in the browser.
"""

from __future__ import annotations

import pytest


class TestProjectEndpoints:
    def test_create_and_get(self, client):
        response = client.post("/api/projects", json={"name": "پروژه تست", "description": "x"})
        assert response.status_code == 201
        project_id = response.json()["id"]

        fetched = client.get(f"/api/projects/{project_id}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "پروژه تست"

    def test_get_nonexistent_returns_persian_404(self, client):
        response = client.get("/api/projects/does-not-exist")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "not_found"
        assert "پیدا نشد" in body["error"]["message"]

    def test_create_validates_empty_name(self, client):
        response = client.post("/api/projects", json={"name": ""})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_list_returns_created_projects(self, client):
        client.post("/api/projects", json={"name": "الف"})
        client.post("/api/projects", json={"name": "ب"})
        response = client.get("/api/projects")
        assert response.status_code == 200
        assert response.json()["total"] >= 2

    def test_update_project(self, client):
        created = client.post("/api/projects", json={"name": "قدیم"}).json()
        response = client.patch(f"/api/projects/{created['id']}", json={"name": "جدید"})
        assert response.json()["name"] == "جدید"

    def test_delete_project(self, client):
        created = client.post("/api/projects", json={"name": "حذف‌شدنی"}).json()
        response = client.delete(f"/api/projects/{created['id']}")
        assert response.status_code == 200
        assert client.get(f"/api/projects/{created['id']}").status_code == 404


class TestDocumentEndpoints:
    def test_create_and_update(self, client):
        project = client.post("/api/projects", json={"name": "test"}).json()
        doc = client.post(
            f"/api/projects/{project['id']}/documents",
            json={"type": "note", "content": "متن اولیه"},
        ).json()
        assert doc["content"] == "متن اولیه"

        updated = client.patch(
            f"/api/projects/{project['id']}/documents/{doc['id']}",
            json={"content": "متن ویرایش‌شده"},
        )
        assert updated.json()["content"] == "متن ویرایش‌شده"

    def test_document_from_wrong_project_is_404(self, client):
        p1 = client.post("/api/projects", json={"name": "p1"}).json()
        p2 = client.post("/api/projects", json={"name": "p2"}).json()
        doc = client.post(
            f"/api/projects/{p1['id']}/documents", json={"type": "note", "content": "x"}
        ).json()
        response = client.get(f"/api/projects/{p2['id']}/documents/{doc['id']}")
        assert response.status_code == 404


class TestSubtitleEndpoints:
    def test_create_track_add_cue_split_merge(self, client):
        project = client.post("/api/projects", json={"name": "test"}).json()
        track = client.post(
            f"/api/projects/{project['id']}/subtitles",
            json={"name": "زیرنویس فارسی", "language": "fa"},
        ).json()

        cue = client.post(
            f"/api/projects/{project['id']}/subtitles/{track['id']}/cues",
            json={"start": 0.0, "end": 4.0, "text": "این یک جمله بلند برای تقسیم است"},
        ).json()

        split = client.post(
            f"/api/projects/{project['id']}/subtitles/{track['id']}/cues/{cue['id']}/split",
            json={"at_seconds": 2.0},
        )
        assert split.status_code == 200
        cues_after_split = split.json()["items"]
        assert len(cues_after_split) == 2

        first_id = cues_after_split[0]["id"]
        merged = client.post(
            f"/api/projects/{project['id']}/subtitles/{track['id']}/cues/{first_id}/merge",
            json={},
        )
        assert merged.status_code == 200
        assert len(merged.json()["items"]) == 1

    def test_update_cue_timing(self, client):
        project = client.post("/api/projects", json={"name": "test"}).json()
        track = client.post(
            f"/api/projects/{project['id']}/subtitles", json={"name": "t"}
        ).json()
        cue = client.post(
            f"/api/projects/{project['id']}/subtitles/{track['id']}/cues",
            json={"start": 0.0, "end": 2.0, "text": "x"},
        ).json()

        updated = client.patch(
            f"/api/projects/{project['id']}/subtitles/{track['id']}/cues/{cue['id']}",
            json={"start": 1.0, "end": 3.5},
        )
        assert updated.json()["start"] == 1.0
        assert updated.json()["end"] == 3.5

    def test_reject_tiny_cue(self, client):
        project = client.post("/api/projects", json={"name": "test"}).json()
        track = client.post(
            f"/api/projects/{project['id']}/subtitles", json={"name": "t"}
        ).json()
        response = client.post(
            f"/api/projects/{project['id']}/subtitles/{track['id']}/cues",
            json={"start": 0.0, "end": 0.01, "text": "x"},
        )
        # ValidationError maps to 422, not 400 - see app/core/errors.py.
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_preview_formats(self, client):
        project = client.post("/api/projects", json={"name": "test"}).json()
        track = client.post(
            f"/api/projects/{project['id']}/subtitles", json={"name": "t"}
        ).json()
        client.post(
            f"/api/projects/{project['id']}/subtitles/{track['id']}/cues",
            json={"start": 0.0, "end": 2.0, "text": "سلام"},
        )
        for fmt in ("srt", "vtt", "ass"):
            response = client.get(
                f"/api/projects/{project['id']}/subtitles/{track['id']}/preview",
                params={"format": fmt},
            )
            assert response.status_code == 200
            assert "سلام" in response.text


class TestAiDiscoveryEndpoints:
    def test_providers_reports_claude(self, client):
        response = client.get("/api/ai/providers")
        assert response.status_code == 200
        ids = {p["id"] for p in response.json()["items"]}
        assert "claude" in ids

    def test_models_endpoint_returns_registry(self, client):
        response = client.get("/api/ai/models")
        assert response.status_code == 200
        ids = {m["id"] for m in response.json()["items"]}
        assert "sonnet" in ids

    def test_recommend_returns_persian_reason(self, client):
        response = client.get("/api/ai/recommend", params={"task": "translation"})
        assert response.status_code == 200
        body = response.json()
        assert body["recommended_model"]
        assert body["reason_fa"].strip()

    def test_tasks_endpoint_lists_every_task(self, client):
        response = client.get("/api/ai/tasks")
        ids = {t["id"] for t in response.json()["items"]}
        assert "translation" in ids
        assert "subtitle_processing" in ids

    def test_prompts_endpoint_returns_builtins(self, client):
        response = client.get("/api/ai/prompts")
        names = {p["id"] for p in response.json()["items"]}
        assert "translate_fa_en" in names

    def test_tts_voices_include_persian(self, client):
        response = client.get("/api/ai/tts/voices", params={"language": "fa"})
        voices = response.json()["items"]
        assert any(v["language"] == "fa" for v in voices)


class TestSettingsEndpoints:
    def test_get_settings_includes_defaults(self, client):
        response = client.get("/api/settings")
        assert "media.audio_preset" in response.json()["values"]

    def test_update_and_persist(self, client):
        client.put("/api/settings", json={"values": {"voice.rate": 1.3}})
        response = client.get("/api/settings")
        assert response.json()["values"]["voice.rate"] == 1.3

    def test_update_rejects_invalid_value(self, client):
        response = client.put("/api/settings", json={"values": {"voice.rate": "fast"}})
        assert response.status_code == 422

    def test_reset_restores_default(self, client):
        client.put("/api/settings", json={"values": {"voice.rate": 1.9}})
        client.post("/api/settings/reset", json={"key": "voice.rate"})
        response = client.get("/api/settings")
        assert response.json()["values"]["voice.rate"] == 1.0


class TestSystemEndpoints:
    def test_health(self, client):
        assert client.get("/api/health").status_code == 200

    def test_status_reports_dependencies(self, client):
        response = client.get("/api/system/status")
        assert response.status_code == 200
        body = response.json()
        assert any(d["id"] == "ffmpeg" for d in body["dependencies"])

    def test_media_capabilities_lists_presets(self, client):
        response = client.get("/api/system/media")
        presets = {p["id"] for p in response.json()["audio_presets"]}
        assert {"opus", "mp3", "wav"}.issubset(presets)


class TestJobEndpoints:
    def test_audio_extract_returns_202_with_job(self, client, ffmpeg_tools):
        project = client.post("/api/projects", json={"name": "test"}).json()
        import_response = client.post(
            f"/api/projects/{project['id']}/assets/import",
            json={"path": "Z:/does/not/exist.mp4", "type": "video"},
        )
        assert import_response.status_code == 400  # validated before any job runs

    def test_unknown_job_is_404(self, client):
        response = client.get("/api/jobs/nonexistent")
        assert response.status_code == 404

    def test_cancel_unknown_job_is_404(self, client):
        response = client.delete("/api/jobs/nonexistent")
        assert response.status_code == 404


class TestFileServing:
    def test_missing_asset_is_404(self, client):
        response = client.get("/api/files/nonexistent")
        assert response.status_code == 404

    def test_asset_streams_with_correct_content_type(
        self, client, container, project, video_asset
    ):
        response = client.get(f"/api/files/{video_asset.id}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("video/")
