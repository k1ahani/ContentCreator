# Database

## Purpose

SQLite persistence: connection management, the migration system, and the
repository pattern that keeps raw SQL confined to one layer.

## Why SQLite

A single-user local application has no concurrent-writer problem to solve, no
network round-trip to hide, and no reason to run a database server the user
would have to install and manage. SQLite is a file (`storage/app.db`), which
also makes backup trivial (copy the file) and inspection easy (any SQLite
browser).

## Connection management

`app/db/connection.py::Database` hands out **thread-local connections** —
each thread (FastAPI's request thread pool, each job worker thread) gets its
own `sqlite3.Connection`, created lazily on first use. `sqlite3` connections
are not safe to share across threads; this is not an optimisation, it's a
correctness requirement.

Every connection is configured with:

- **`PRAGMA journal_mode = WAL`** — readers never block the writer, which is
  what lets the frontend poll job state while a worker thread is mid-write to
  the same job's row.
- **`PRAGMA foreign_keys = ON`** — SQLite disables foreign key enforcement per
  connection by default; without this, `ON DELETE CASCADE` on a project's
  children (assets, documents, subtitle tracks, jobs) would silently do
  nothing, and deleting a project would leave orphaned rows.
- **`PRAGMA busy_timeout = 5000`** — under WAL a second writer still briefly
  waits; 5 seconds is generously longer than any write this application
  performs.

Timestamps are stored as ISO-8601 UTC strings via a registered
`sqlite3` adapter/converter pair (`_adapt_datetime`/`_convert_timestamp`), so
every repository gets back real timezone-aware `datetime` objects, never a
raw string to parse manually.

## Migrations

`app/db/migrations/`. Forward-only, plain `.sql` files named
`NNNN_description.sql` in `versions/`, applied in filename order, each inside
its own transaction, recorded in a `schema_migrations` table.

**Why no down-migrations.** This is a local single-user application with no
staged rollout, no multiple environments to keep in sync, and one database
file per install. A reversible migration system is real machinery that earns
its cost when multiple people or environments need to move a schema backward
in lockstep — none of that applies here. To undo a migration during
development, restore the database file from backup, or delete
`storage/app.db` to start clean (the app recreates it from scratch on next
startup).

**Statement splitting** (`runner.py::split_statements`) is hand-written
rather than using `sqlite3.Connection.executescript`, because
`executescript` implicitly commits any open transaction before running —
which would defeat the per-migration atomicity this system depends on (each
migration's connection has an explicit `BEGIN` open under
`isolation_level=None`). The splitter is string-literal-aware (handles `--`
comments and `''`-escaped quotes inside string literals) and intentionally
does **not** support `BEGIN...END` trigger bodies — migrations that need
trigger logic should express it in application code instead.

## Adding a migration

Drop a new file with the next sequential number into
`app/db/migrations/versions/`. The runner picks it up automatically on next
startup; `migrate()` is idempotent (already-applied versions are skipped by
checking `schema_migrations`).

```sql
-- app/db/migrations/versions/0002_add_something.sql
ALTER TABLE projects ADD COLUMN something TEXT NOT NULL DEFAULT '';
```

Never edit an already-applied migration file in `versions/` — write a new one
instead. Editing a past migration changes nothing for databases that already
ran it, which silently desyncs schema history from what's on disk for
existing installs.

### Changing a `CHECK` constraint (adding an enum value)

Enum-valued columns are constrained with `CHECK`, so adding a member to an enum
in `app/domain/enums.py` — a new `JobType`, `AssetType`, `DocumentType` — needs
a migration, or the database rejects the first row that uses it. SQLite cannot
alter a `CHECK` in place; the documented workaround is to rebuild the table.

`versions/0002_subtitle_sync_job.sql` is the worked example, and **the ordering
in it is load-bearing**. Foreign keys are ON for every connection, and
`job_logs` references `jobs` with `ON DELETE CASCADE`. Under those two facts
`DROP TABLE jobs` performs an implicit delete of every row first, which cascades
and silently erases the whole console-log history. So the child table is rebuilt
and re-pointed *before* the parent is dropped:

```sql
CREATE TABLE jobs_new (...);              -- new definition
INSERT INTO jobs_new SELECT ... FROM jobs;
CREATE TABLE job_logs_new (... REFERENCES jobs_new (id) ON DELETE CASCADE);
INSERT INTO job_logs_new SELECT ... FROM job_logs;
DROP TABLE job_logs;                       -- no children, safe
DROP TABLE jobs;                           -- now childless, nothing to cascade
ALTER TABLE jobs_new RENAME TO jobs;       -- SQLite rewrites job_logs_new's FK
ALTER TABLE job_logs_new RENAME TO job_logs;
-- indexes went with the dropped tables; recreate them
```

The renames rely on SQLite ≥3.25 rewriting foreign keys that point at a renamed
table, which is what leaves `job_logs` referencing `jobs` again at the end.
Verify a rebuild with `PRAGMA foreign_key_check` and a row count before and
after — a migration that quietly drops rows is the failure mode here.

## Repositories

`app/db/repositories/` — **the only place raw SQL is written.** One
repository per aggregate (`ProjectRepository`, `AssetRepository`,
`DocumentRepository`, `SubtitleRepository`, `JobRepository`,
`SettingsRepository`, `PromptRepository`), each owning the mapping from
`sqlite3.Row` to the corresponding domain model in `app/domain/`.

Services and job handlers compose repositories; **API routers never touch
SQL** — they go through `ServiceContainer` properties
(`container.projects`, `container.assets`, etc.), which construct a fresh
repository per access (cheap — repositories hold no state beyond the shared
`Database` handle, so this is correct even across the thread-local connection
boundary).

JSON-shaped columns (`metadata`, `style`, `input`/`output` on jobs) go through
`app/db/connection.py::dumps`/`loads` — `dumps` uses `ensure_ascii=False` so
Persian text stays human-readable when inspecting the database file directly
with any SQLite tool, rather than being escaped into `\uXXXX` sequences.

## Adding a database entity

1. Write a migration creating the table (`versions/000N_....sql`), with a
   `CHECK` constraint on any enum-valued column — a typo in application code
   should fail loudly at the database level, not silently write an
   unreadable row.
2. Add a domain model in `app/domain/` (pure Pydantic, no DB knowledge).
3. Add a repository in `app/db/repositories/`, following the existing pattern
   (`create`, `get`, `list`, `update`, `delete`, plus whatever's specific to
   the entity). Add it to `app/db/repositories/__init__.py`'s exports.
4. Expose it on `ServiceContainer` as a property (`app/container.py`), the way
   every other repository is exposed.
5. If it's user-facing, add API schemas and a router — see `docs/API.md`.

## Common mistakes

- **Writing SQL outside `app/db/repositories/`.** If you find yourself
  writing `db.execute(...)` in a job handler or an API router, that SQL
  belongs in a repository method instead.
- **Assuming `metadata`/`style`/JSON columns round-trip as dicts without
  `loads`.** They're stored as TEXT; always go through the connection
  module's `dumps`/`loads` helpers, which also handle a `NULL`/malformed value
  gracefully by falling back to an empty dict rather than raising.
- **Editing a migration that's already shipped.** Write a new one instead —
  see the migrations section above.

## Testing

`backend/tests/unit/test_database.py` runs every repository against a real
temporary SQLite database (migrated the same way production is) — cascade
deletes, cue reindexing after insert/delete, document version chaining,
Persian text round-tripping, and the statement splitter's handling of
string literals and comments are all covered against actual SQLite behaviour,
not a mock.
