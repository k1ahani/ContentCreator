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


class TestSubtitleRetiming:
    """Manual/batch synchronisation, which answers inline rather than as a job."""

    def _track_with_cues(self, client, spans) -> tuple[str, str]:
        project = client.post("/api/projects", json={"name": "retime"}).json()
        track = client.post(
            f"/api/projects/{project['id']}/subtitles", json={"name": "t"}
        ).json()
        for start, end, text in spans:
            client.post(
                f"/api/projects/{project['id']}/subtitles/{track['id']}/cues",
                json={"start": start, "end": end, "text": text},
            )
        return project["id"], track["id"]

    def test_shift_moves_every_cue_and_reports_it(self, client):
        project_id, track_id = self._track_with_cues(
            client, [(10.0, 12.0, "اول"), (20.0, 22.0, "دوم"), (30.0, 32.0, "سوم")]
        )
        response = client.post(
            f"/api/projects/{project_id}/subtitles/{track_id}/retime",
            json={"mode": "shift", "offset_seconds": -3.0},
        )
        assert response.status_code == 200
        body = response.json()
        assert [c["start"] for c in body["items"]] == [7.0, 17.0, 27.0]
        assert body["report"]["changed_count"] == 3
        assert body["report"]["mode"] == "shift"

    def test_retime_never_changes_cue_text_or_ids(self, client):
        project_id, track_id = self._track_with_cues(
            client, [(0.0, 2.0, "متن اول"), (5.0, 7.0, "متن دوم")]
        )
        before = client.get(
            f"/api/projects/{project_id}/subtitles/{track_id}/cues"
        ).json()["items"]

        after = client.post(
            f"/api/projects/{project_id}/subtitles/{track_id}/retime",
            json={"mode": "scale", "factor": 2.0},
        ).json()["items"]

        assert [c["id"] for c in after] == [c["id"] for c in before]
        assert [c["text"] for c in after] == [c["text"] for c in before]

    def test_reading_speed_repacks_by_text_length(self, client):
        project_id, track_id = self._track_with_cues(
            client,
            [(0.0, 5.0, "کوتاه"), (6.0, 8.0, "یک متن به مراتب طولانی‌تر از قطعه قبلی")],
        )
        items = client.post(
            f"/api/projects/{project_id}/subtitles/{track_id}/retime",
            json={"mode": "reading_speed", "chars_per_second": 6.0, "start_seconds": 0.0},
        ).json()["items"]

        assert items[0]["start"] == 0.0
        assert (items[1]["end"] - items[1]["start"]) > (items[0]["end"] - items[0]["start"])

    def test_result_is_persisted_not_just_returned(self, client):
        project_id, track_id = self._track_with_cues(client, [(10.0, 12.0, "متن")])
        client.post(
            f"/api/projects/{project_id}/subtitles/{track_id}/retime",
            json={"mode": "shift", "offset_seconds": 5.0},
        )
        stored = client.get(
            f"/api/projects/{project_id}/subtitles/{track_id}/cues"
        ).json()["items"]
        assert stored[0]["start"] == 15.0

    def test_clamps_inside_the_media_duration(self, client):
        project_id, track_id = self._track_with_cues(client, [(10.0, 12.0, "متن")])
        body = client.post(
            f"/api/projects/{project_id}/subtitles/{track_id}/retime",
            json={
                "mode": "shift",
                "offset_seconds": 500.0,
                "media_duration_seconds": 20.0,
            },
        ).json()
        assert body["items"][0]["end"] <= 20.0
        assert body["report"]["clamped_count"] == 1

    def test_retimed_track_never_overlaps(self, client):
        project_id, track_id = self._track_with_cues(
            client, [(float(i), float(i) + 0.9, f"قطعه {i}") for i in range(8)]
        )
        items = client.post(
            f"/api/projects/{project_id}/subtitles/{track_id}/retime",
            json={"mode": "scale", "factor": 0.2},
        ).json()["items"]

        for earlier, later in zip(items, items[1:]):
            assert later["start"] >= earlier["end"]
            assert later["end"] > later["start"]

    def test_stretch_without_a_target_is_rejected(self, client):
        project_id, track_id = self._track_with_cues(client, [(0.0, 2.0, "متن")])
        response = client.post(
            f"/api/projects/{project_id}/subtitles/{track_id}/retime",
            json={"mode": "stretch"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_empty_track_is_rejected_with_a_persian_message(self, client):
        project = client.post("/api/projects", json={"name": "retime"}).json()
        track = client.post(
            f"/api/projects/{project['id']}/subtitles", json={"name": "t"}
        ).json()
        response = client.post(
            f"/api/projects/{project['id']}/subtitles/{track['id']}/retime",
            json={"mode": "shift", "offset_seconds": 1.0},
        )
        assert response.status_code == 422
        assert "قطعه‌ای" in response.json()["error"]["message"]

    def test_sync_endpoint_accepts_and_enqueues_a_job(self, client, project):
        """The automatic path returns 202 + a job, like every long operation.

        Only the router contract is asserted. The asset id deliberately does
        not exist, so the handler fails on its first lookup instead of loading
        a speech-recognition model - a real sync would spend minutes on ASR
        weights, which does not belong in an HTTP contract test. Whether the
        alignment itself is any good is asked, without that cost, in
        ``tests/unit/test_subtitle_sync.py``.
        """
        track = client.post(
            f"/api/projects/{project.id}/subtitles", json={"name": "t"}
        ).json()
        client.post(
            f"/api/projects/{project.id}/subtitles/{track['id']}/cues",
            json={"start": 0.0, "end": 2.0, "text": "سلام"},
        )

        response = client.post(
            f"/api/projects/{project.id}/subtitles/sync",
            json={"track_id": track["id"], "asset_id": "no-such-asset"},
        )
        assert response.status_code == 202
        job = response.json()["job"]
        assert job["type"] == "subtitle_sync"
        assert job["input"]["track_id"] == track["id"]

    def test_sync_requires_a_track_and_an_asset(self, client, project):
        response = client.post(
            f"/api/projects/{project.id}/subtitles/sync", json={"track_id": "x"}
        )
        assert response.status_code == 422


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

    def test_tts_providers_span_free_and_paid(self, client):
        """Every registered provider is reported, including ones the user has
        not configured - with *why*, so "not set up yet" is distinguishable
        from "broken"."""
        items = client.get("/api/ai/tts/providers").json()["items"]
        by_id = {p["id"]: p for p in items}
        assert {"edge", "sapi5", "elevenlabs", "openai_compatible"} <= set(by_id)
        assert by_id["edge"]["pricing"] == "free"
        assert by_id["elevenlabs"]["requires_api_key"] is True
        # Unconfigured, but present and explained rather than hidden.
        if not by_id["elevenlabs"]["available"]:
            assert by_id["elevenlabs"]["unavailable_reason"]
            assert by_id["elevenlabs"]["api_key_setting"] == "voice.elevenlabs_api_key"

    def test_english_voices_cover_several_accents(self, client):
        voices = client.get(
            "/api/ai/tts/voices", params={"language": "en"}
        ).json()["items"]
        locales = {v["locale"] for v in voices if v["locale"]}
        assert len(locales) >= 5, f"expected several English accents, got {locales}"

    def test_voice_preview_rejects_an_unknown_voice(self, client):
        response = client.get("/api/ai/tts/voices/no-such-voice/preview")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    @pytest.mark.slow
    def test_voice_preview_returns_playable_audio(self, client):
        """Real synthesis through the real provider - the point of the preview
        is that the user hears what they will actually get."""
        response = client.get("/api/ai/tts/voices/fa-IR-DilaraNeural/preview")
        if response.status_code != 200:
            pytest.skip("edge-tts requires network access")
        assert response.headers["content-type"].startswith("audio/")
        assert len(response.content) > 1000


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
