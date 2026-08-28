"""SQLite connection management.

Design notes that matter for this application:

* **Thread-local connections.** FastAPI serves requests on a thread pool and
  the job workers are their own threads. ``sqlite3`` connections are not safe
  to share across threads, so each thread gets its own, opened lazily.
* **WAL journal.** Readers never block the writer, which is what lets the UI
  poll job state while a handler is writing progress.
* **Foreign keys ON.** SQLite disables them per-connection by default; without
  this, ``ON DELETE CASCADE`` on project children silently does nothing.
* **``busy_timeout``.** Under WAL a second writer still has to wait. Five
  seconds is far longer than any write this application performs.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.core.logging import get_logger

logger = get_logger(__name__)


def _adapt_datetime(value: datetime) -> str:
    """Store timestamps as ISO-8601 UTC strings."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _convert_timestamp(raw: bytes) -> datetime:
    text = raw.decode("utf-8")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.fromisoformat(text.replace(" ", "T"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_converter("TIMESTAMP", _convert_timestamp)


def utcnow() -> datetime:
    """Timezone-aware current time. Use this instead of ``datetime.utcnow``."""
    return datetime.now(timezone.utc)


def dumps(value: Any) -> str:
    """JSON encode for a TEXT column. ``ensure_ascii=False`` keeps Persian
    readable when inspecting the database by hand."""
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(raw: str | None, fallback: Any = None) -> Any:
    if not raw:
        return {} if fallback is None else fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("could not decode JSON column, using fallback")
        return {} if fallback is None else fallback


class Database:
    """Owns the SQLite file and hands out per-thread connections."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._all_connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

    # -- connection lifecycle ---------------------------------------------

    @property
    def connection(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
            with self._lock:
                self._all_connections.append(conn)
        return conn

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,  # explicit transactions via the context manager
            timeout=5.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def close(self) -> None:
        """Close every connection handed out. Called on application shutdown."""
        with self._lock:
            for conn in self._all_connections:
                try:
                    conn.close()
                except sqlite3.Error:  # pragma: no cover - best effort
                    pass
            self._all_connections.clear()
        self._local = threading.local()

    # -- query helpers -----------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block inside a single transaction.

        Nested use is not supported and not needed; repositories take a
        connection argument so a service can compose several writes into one
        transaction explicitly.
        """
        conn = self.connection
        conn.execute("BEGIN")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, params)

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.connection.execute(sql, params).fetchone()

    def query_all(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self.connection.execute(sql, params).fetchall()
