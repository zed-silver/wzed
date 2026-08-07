"""Transcription history: SQLite + FTS5, searchable."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from wzed.config import DB_PATH


class HistoryStore:
    def __init__(self, path: Path = DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY,
                ts REAL NOT NULL,
                app TEXT,
                lang TEXT,
                raw TEXT NOT NULL,
                final TEXT NOT NULL,
                latency_ms REAL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts
                USING fts5(final, content=entries, content_rowid=id);
            CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
                INSERT INTO entries_fts(rowid, final) VALUES (new.id, new.final);
            END;
            """
        )
        self._db.commit()

    def add(
        self,
        raw: str,
        final: str,
        app: str | None = None,
        lang: str | None = None,
        latency_ms: float | None = None,
    ) -> None:
        self._db.execute(
            "INSERT INTO entries (ts, app, lang, raw, final, latency_ms) VALUES (?,?,?,?,?,?)",
            (time.time(), app, lang, raw, final, latency_ms),
        )
        self._db.commit()

    def search(self, query: str, limit: int = 50) -> list[tuple]:
        if not query.strip():
            return self.recent(limit)
        return self._db.execute(
            """SELECT e.ts, e.app, e.final FROM entries_fts f
               JOIN entries e ON e.id = f.rowid
               WHERE entries_fts MATCH ? ORDER BY e.ts DESC LIMIT ?""",
            (query, limit),
        ).fetchall()

    def recent(self, limit: int = 50) -> list[tuple]:
        return self._db.execute(
            "SELECT ts, app, final FROM entries ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()

    def close(self) -> None:
        self._db.close()
