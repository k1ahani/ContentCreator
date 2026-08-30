-- Allow the 'subtitle_sync' job type (audio-based subtitle synchronisation).
--
-- Why this is a whole table rebuild for one enum value: the `type` column
-- carries a CHECK constraint listing every job type (the convention described
-- in docs/DATABASE.md), and SQLite has no way to alter a CHECK in place. The
-- documented workaround is to build the table again with the new definition
-- and copy the rows across.
--
-- The order below is not arbitrary. `job_logs` has a foreign key onto `jobs`
-- with ON DELETE CASCADE, and foreign keys are ON for every connection
-- (app/db/connection.py). Under those two facts, `DROP TABLE jobs` performs an
-- implicit DELETE of every row first, which would cascade and silently erase
-- the entire console-log history. So `job_logs` is rebuilt and detached
-- *before* `jobs` is dropped, and the renames are sequenced so SQLite's
-- automatic reference rewriting (ALTER TABLE ... RENAME updates foreign keys
-- pointing at the renamed table) leaves job_logs pointing back at `jobs`.

CREATE TABLE jobs_new (
    id           TEXT PRIMARY KEY,
    project_id   TEXT REFERENCES projects (id) ON DELETE CASCADE,
    type         TEXT NOT NULL
                 CHECK (type IN ('audio_extract', 'transcribe', 'text_task',
                                 'subtitle_generate', 'subtitle_sync',
                                 'subtitle_render', 'tts_synthesize')),
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

INSERT INTO jobs_new (id, project_id, type, status, progress, stage, provider,
                      model, input, output, error, error_code, created_at,
                      started_at, finished_at)
SELECT id, project_id, type, status, progress, stage, provider, model, input,
       output, error, error_code, created_at, started_at, finished_at
FROM jobs;

-- Re-point the log table at the new jobs table before the old one is dropped,
-- so the cascade above never has anything to cascade into.
CREATE TABLE job_logs_new (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id   TEXT NOT NULL REFERENCES jobs_new (id) ON DELETE CASCADE,
    ts       REAL NOT NULL,
    stream   TEXT NOT NULL DEFAULT 'stdout'
             CHECK (stream IN ('stdout', 'stderr', 'system')),
    text     TEXT NOT NULL
);

INSERT INTO job_logs_new (id, job_id, ts, stream, text)
SELECT id, job_id, ts, stream, text FROM job_logs;

DROP TABLE job_logs;
DROP TABLE jobs;

ALTER TABLE jobs_new RENAME TO jobs;
ALTER TABLE job_logs_new RENAME TO job_logs;

CREATE INDEX idx_jobs_project ON jobs (project_id, created_at DESC);
CREATE INDEX idx_jobs_status ON jobs (status, created_at);
CREATE INDEX idx_job_logs_job ON job_logs (job_id, id);
