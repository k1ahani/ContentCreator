"""Database layer tests: migrations, repositories, cascades, Persian text."""

from __future__ import annotations

import pytest

from app.db.connection import Database
from app.db.migrations.runner import migrate, split_statements
from app.db.repositories import (
    AssetRepository,
    DocumentRepository,
    JobRepository,
    ProjectRepository,
    SettingsRepository,
    SubtitleRepository,
)
from app.domain.document import DocumentCreate
from app.domain.enums import AssetType, DocumentType, JobType, Language
from app.domain.job import JobCreate, JobLogLine
from app.domain.project import ProjectCreate, ProjectUpdate
from app.domain.subtitle import CueCreate, SubtitleStyle, TrackCreate


@pytest.fixture
def db(tmp_path) -> Database:
    instance = Database(tmp_path / "test.db")
    migrate(instance)
    return instance


class TestMigrations:
    def test_idempotent_rerun_applies_nothing(self, db: Database):
        assert migrate(db) == []

    def test_statement_splitter_respects_string_literals(self):
        sql = "INSERT INTO t VALUES ('a;b'); INSERT INTO t VALUES ('c''d;e');"
        statements = split_statements(sql)
        assert len(statements) == 2
        assert "a;b" in statements[0]
        assert "c''d;e" in statements[1]

    def test_statement_splitter_ignores_comments(self):
        sql = "-- comment; with semicolon\nINSERT INTO t VALUES (1);"
        statements = split_statements(sql)
        assert len(statements) == 1


class TestProjectRepository:
    def test_create_and_get_round_trip(self, db: Database):
        repo = ProjectRepository(db)
        created = repo.create(ProjectCreate(name="آموزش React", description="توضیح"))
        fetched = repo.get(created.id)
        assert fetched.name == "آموزش React"
        assert fetched.created_at.tzinfo is not None

    def test_list_orders_by_recent_activity(self, db: Database):
        repo = ProjectRepository(db)
        first = repo.create(ProjectCreate(name="اول"))
        second = repo.create(ProjectCreate(name="دوم"))
        repo.touch(first.id)
        items = repo.list()
        assert items[0].id == first.id

    def test_search_matches_name(self, db: Database):
        repo = ProjectRepository(db)
        repo.create(ProjectCreate(name="پروژه ویدیو"))
        repo.create(ProjectCreate(name="چیز دیگر"))
        results = repo.list(search="ویدیو")
        assert len(results) == 1

    def test_update_bumps_timestamp(self, db: Database):
        repo = ProjectRepository(db)
        project = repo.create(ProjectCreate(name="اول"))
        updated = repo.update(project.id, ProjectUpdate(name="جدید"))
        assert updated.name == "جدید"
        assert updated.updated_at >= project.created_at

    def test_counters_reflect_children(self, db: Database):
        projects = ProjectRepository(db)
        assets = AssetRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        assets.create(
            project_id=project.id, type=AssetType.VIDEO, path=__import__("pathlib").Path("x.mp4"),
            original_filename="x.mp4",
        )
        assert projects.get(project.id).asset_count == 1

    def test_delete_cascades_to_children(self, db: Database):
        from pathlib import Path

        projects = ProjectRepository(db)
        assets = AssetRepository(db)
        documents = DocumentRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        assets.create(
            project_id=project.id, type=AssetType.VIDEO, path=Path("x.mp4"),
            original_filename="x.mp4",
        )
        documents.create(project.id, DocumentCreate(type=DocumentType.NOTE, content="x"))

        assert projects.delete(project.id) is True
        assert assets.list_for_project(project.id) == []
        assert documents.list_for_project(project.id) == []


class TestDocumentRepository:
    def test_version_increments_from_source(self, db: Database):
        projects = ProjectRepository(db)
        documents = DocumentRepository(db)
        project = projects.create(ProjectCreate(name="test"))

        original = documents.create(
            project.id, DocumentCreate(type=DocumentType.TRANSCRIPT_RAW, content="متن اول")
        )
        derived = documents.create(
            project.id,
            DocumentCreate(
                type=DocumentType.EDITED, content="متن دوم", source_document_id=original.id
            ),
        )
        assert original.version == 1
        assert derived.version == 2

    def test_original_never_mutated_by_derived_document(self, db: Database):
        projects = ProjectRepository(db)
        documents = DocumentRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        original = documents.create(
            project.id, DocumentCreate(type=DocumentType.TRANSCRIPT_RAW, content="اصل")
        )
        documents.create(
            project.id,
            DocumentCreate(type=DocumentType.EDITED, content="تغییر یافته",
                          source_document_id=original.id),
        )
        assert documents.get(original.id).content == "اصل"

    def test_persian_text_round_trips_exactly(self, db: Database):
        projects = ProjectRepository(db)
        documents = DocumentRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        text = "می‌شود؛ این متنی با نیم‌فاصله و علائم فارسی، است؟"
        created = documents.create(
            project.id, DocumentCreate(type=DocumentType.NOTE, content=text, language=Language.PERSIAN)
        )
        assert documents.get(created.id).content == text


class TestSubtitleRepository:
    def test_replace_cues_atomic_swap(self, db: Database):
        projects = ProjectRepository(db)
        subtitles = SubtitleRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        track = subtitles.create_track(project.id, TrackCreate(name="t"))

        subtitles.replace_cues(track.id, [CueCreate(start=0.0, end=1.0, text="a")])
        subtitles.replace_cues(
            track.id,
            [CueCreate(start=0.0, end=1.0, text="x"), CueCreate(start=1.0, end=2.0, text="y")],
        )
        cues = subtitles.list_cues(track.id)
        assert [c.text for c in cues] == ["x", "y"]

    def test_add_cue_at_index_shifts_following_cues(self, db: Database):
        projects = ProjectRepository(db)
        subtitles = SubtitleRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        track = subtitles.create_track(project.id, TrackCreate(name="t"))
        subtitles.replace_cues(
            track.id,
            [CueCreate(start=0.0, end=1.0, text="a"), CueCreate(start=1.0, end=2.0, text="b")],
        )
        cues = subtitles.list_cues(track.id)
        subtitles.add_cue(
            track.id, CueCreate(start=0.5, end=0.8, text="inserted", index=1)
        )
        ordered = subtitles.list_cues(track.id)
        assert [c.text for c in ordered] == ["a", "inserted", "b"]
        assert [c.index for c in ordered] == [0, 1, 2]

    def test_delete_cue_reindexes_following(self, db: Database):
        projects = ProjectRepository(db)
        subtitles = SubtitleRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        track = subtitles.create_track(project.id, TrackCreate(name="t"))
        cues = subtitles.replace_cues(
            track.id,
            [
                CueCreate(start=0.0, end=1.0, text="a"),
                CueCreate(start=1.0, end=2.0, text="b"),
                CueCreate(start=2.0, end=3.0, text="c"),
            ],
        )
        subtitles.delete_cue(cues[0].id)
        remaining = subtitles.list_cues(track.id)
        assert [c.index for c in remaining] == [0, 1]
        assert [c.text for c in remaining] == ["b", "c"]

    def test_style_persists_through_round_trip(self, db: Database):
        projects = ProjectRepository(db)
        subtitles = SubtitleRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        track = subtitles.create_track(
            project.id,
            TrackCreate(name="t", style=SubtitleStyle(font_size=40, text_color="#FF0000")),
        )
        fetched = subtitles.get_track(track.id)
        assert fetched.style.font_size == 40
        assert fetched.style.text_color == "#FF0000"

    def test_track_deletion_cascades_to_cues(self, db: Database):
        projects = ProjectRepository(db)
        subtitles = SubtitleRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        track = subtitles.create_track(project.id, TrackCreate(name="t"))
        subtitles.replace_cues(track.id, [CueCreate(start=0.0, end=1.0, text="a")])
        subtitles.delete_track(track.id)
        # Cues table has no direct query without a track, but count via raw SQL.
        row = db.query_one("SELECT COUNT(*) AS n FROM subtitle_cues")
        assert row["n"] == 0


class TestJobRepository:
    def test_lifecycle_transitions(self, db: Database):
        projects = ProjectRepository(db)
        jobs = JobRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        job = jobs.create(JobCreate(type=JobType.AUDIO_EXTRACT, project_id=project.id))

        assert job.status.value == "queued"
        jobs.mark_running(job.id)
        assert jobs.get(job.id).status.value == "running"
        jobs.mark_completed(job.id, {"result": "ok"})
        final = jobs.get(job.id)
        assert final.status.value == "completed"
        assert final.output == {"result": "ok"}
        assert final.finished_at is not None

    def test_mark_running_only_from_queued(self, db: Database):
        projects = ProjectRepository(db)
        jobs = JobRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        job = jobs.create(JobCreate(type=JobType.AUDIO_EXTRACT, project_id=project.id))
        jobs.mark_cancelled(job.id)
        jobs.mark_running(job.id)  # should be a no-op: status stays cancelled
        assert jobs.get(job.id).status.value == "cancelled"

    def test_logs_ordered_by_insertion(self, db: Database):
        projects = ProjectRepository(db)
        jobs = JobRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        job = jobs.create(JobCreate(type=JobType.AUDIO_EXTRACT, project_id=project.id))
        jobs.append_logs(job.id, [
            JobLogLine(ts=1.0, stream="stdout", text="first"),
            JobLogLine(ts=2.0, stream="stdout", text="second"),
        ])
        lines = jobs.get_logs(job.id)
        assert [l.text for l in lines] == ["first", "second"]

    def test_requeue_orphans_fails_stuck_jobs(self, db: Database):
        projects = ProjectRepository(db)
        jobs = JobRepository(db)
        project = projects.create(ProjectCreate(name="test"))
        job = jobs.create(JobCreate(type=JobType.AUDIO_EXTRACT, project_id=project.id))
        jobs.mark_running(job.id)
        count = jobs.requeue_orphans()
        assert count == 1
        assert jobs.get(job.id).status.value == "failed"
        assert jobs.get(job.id).error_code == "interrupted"


class TestSettingsRepository:
    def test_set_and_get_json_value(self, db: Database):
        repo = SettingsRepository(db)
        repo.set("test.key", {"nested": ["a", "b"], "n": 1})
        assert repo.get("test.key") == {"nested": ["a", "b"], "n": 1}

    def test_upsert_overwrites(self, db: Database):
        repo = SettingsRepository(db)
        repo.set("k", "first")
        repo.set("k", "second")
        assert repo.get("k") == "second"

    def test_missing_key_returns_default(self, db: Database):
        repo = SettingsRepository(db)
        assert repo.get("nope", "fallback") == "fallback"
