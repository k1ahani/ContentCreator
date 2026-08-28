-- Initial schema for the Local AI Content Creator Platform.
--
-- Conventions used throughout:
--   * ids are 16-character sortable strings (app/core/ids.py)
--   * timestamps are ISO-8601 UTC TEXT, declared TIMESTAMP so the sqlite3
--     converter in app/db/connection.py returns aware datetimes
--   * structured blobs are JSON TEXT; binary media never lives in the database
--   * enum-valued columns are constrained with CHECK so a typo in application
--     code fails loudly instead of writing an unreadable row

CREATE TABLE projects (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('draft', 'active', 'completed', 'archived')),
    created_at   TIMESTAMP NOT NULL,
    updated_at   TIMESTAMP NOT NULL
);

CREATE INDEX idx_projects_updated ON projects (updated_at DESC);
CREATE INDEX idx_projects_status ON projects (status);

CREATE TABLE media_assets (
    id                 TEXT PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    type               TEXT NOT NULL
                       CHECK (type IN ('video', 'audio', 'transcript', 'subtitle',
                                       'voice', 'rendered_video')),
    original_filename  TEXT NOT NULL,
    path               TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL DEFAULT 0,
    format             TEXT NOT NULL DEFAULT '',
    duration_seconds   REAL,
    metadata           TEXT NOT NULL DEFAULT '{}',
    created_at         TIMESTAMP NOT NULL
);

CREATE INDEX idx_assets_project ON media_assets (project_id, type, created_at DESC);

CREATE TABLE text_documents (
    id                  TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    type                TEXT NOT NULL
                        CHECK (type IN ('transcript_raw', 'transcript_refined', 'edited',
                                        'translation', 'speech_script', 'note')),
    title               TEXT NOT NULL DEFAULT '',
    content             TEXT NOT NULL DEFAULT '',
    language            TEXT NOT NULL DEFAULT 'fa',
    version             INTEGER NOT NULL DEFAULT 1,
    source_document_id  TEXT REFERENCES text_documents (id) ON DELETE SET NULL,
    created_at          TIMESTAMP NOT NULL,
    updated_at          TIMESTAMP NOT NULL
);

CREATE INDEX idx_documents_project ON text_documents (project_id, type, updated_at DESC);
CREATE INDEX idx_documents_source ON text_documents (source_document_id);

CREATE TABLE subtitle_tracks (
    id                  TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    name                TEXT NOT NULL DEFAULT '',
    language            TEXT NOT NULL DEFAULT 'fa',
    style               TEXT NOT NULL DEFAULT '{}',
    source_document_id  TEXT REFERENCES text_documents (id) ON DELETE SET NULL,
    created_at          TIMESTAMP NOT NULL,
    updated_at          TIMESTAMP NOT NULL
);

CREATE INDEX idx_tracks_project ON subtitle_tracks (project_id, updated_at DESC);

CREATE TABLE subtitle_cues (
    id               TEXT PRIMARY KEY,
    track_id         TEXT NOT NULL REFERENCES subtitle_tracks (id) ON DELETE CASCADE,
    idx              INTEGER NOT NULL DEFAULT 0,
    start_seconds    REAL NOT NULL,
    end_seconds      REAL NOT NULL,
    text             TEXT NOT NULL DEFAULT '',
    style_overrides  TEXT NOT NULL DEFAULT '{}',
    metadata         TEXT NOT NULL DEFAULT '{}',
    CHECK (end_seconds > start_seconds)
);

-- Cues are read in timeline order constantly (editor, preview, render).
CREATE INDEX idx_cues_track_order ON subtitle_cues (track_id, idx);
CREATE INDEX idx_cues_track_time ON subtitle_cues (track_id, start_seconds);

CREATE TABLE jobs (
    id           TEXT PRIMARY KEY,
    project_id   TEXT REFERENCES projects (id) ON DELETE CASCADE,
    type         TEXT NOT NULL
                 CHECK (type IN ('audio_extract', 'transcribe', 'text_task',
                                 'subtitle_generate', 'subtitle_render', 'tts_synthesize')),
    status       TEXT NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    progress     REAL,
    stage        TEXT NOT NULL DEFAULT '',
    provider     TEXT,
    model        TEXT,
    input        TEXT NOT NULL DEFAULT '{}',
    output       TEXT NOT NULL DEFAULT '{}',
    error        TEXT,
    error_code   TEXT,
    created_at   TIMESTAMP NOT NULL,
    started_at   TIMESTAMP,
    finished_at  TIMESTAMP
);

CREATE INDEX idx_jobs_project ON jobs (project_id, created_at DESC);
CREATE INDEX idx_jobs_status ON jobs (status, created_at);

-- Job output lines. Retained so the CLI console can be reopened after the job
-- has finished; trimmed by app/services/maintenance on a retention policy.
CREATE TABLE job_logs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id   TEXT NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    ts       REAL NOT NULL,
    stream   TEXT NOT NULL DEFAULT 'stdout'
             CHECK (stream IN ('stdout', 'stderr', 'system')),
    text     TEXT NOT NULL
);

CREATE INDEX idx_job_logs_job ON job_logs (job_id, id);

-- Key/value settings. Values are JSON so a setting can be a scalar, a list or
-- a nested object (for example per-task model preferences) without a schema
-- change. Defaults live in app/services/settings.py, not here, so that adding
-- a setting never needs a migration.
CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMP NOT NULL
);

-- Reusable prompts. Version 1 ships the built-in library read-only from code
-- and stores user-created prompts here; the table already carries the columns
-- the planned template/variable system needs.
CREATE TABLE prompts (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'general',
    task        TEXT NOT NULL DEFAULT 'general',
    body        TEXT NOT NULL,
    variables   TEXT NOT NULL DEFAULT '[]',
    is_builtin  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP NOT NULL,
    updated_at  TIMESTAMP NOT NULL
);

CREATE INDEX idx_prompts_task ON prompts (task, name);
