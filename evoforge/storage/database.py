"""SQLite metadata and idempotent metrics. Large tensors remain on disk."""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1


class Database:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / ".evoforge.sqlite"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError(f"Unsupported database version: {version}")
            if version == 0:
                for statement in (
                    """CREATE TABLE experiments (id TEXT PRIMARY KEY, config TEXT NOT NULL,
                       status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                       game_version TEXT NOT NULL, algorithm_version INTEGER NOT NULL DEFAULT 1,
                       archived INTEGER NOT NULL DEFAULT 0)""",
                    """CREATE TABLE workers (experiment TEXT PRIMARY KEY REFERENCES experiments(id),
                       identity TEXT NOT NULL, pid INTEGER, incarnation TEXT, heartbeat REAL NOT NULL,
                       request TEXT, error TEXT, generation INTEGER NOT NULL DEFAULT 0)""",
                    """CREATE TABLE metrics (experiment TEXT NOT NULL REFERENCES experiments(id),
                       generation INTEGER NOT NULL, data TEXT NOT NULL,
                       PRIMARY KEY(experiment,generation))""",
                    """CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL,
                       experiment TEXT NOT NULL, type TEXT NOT NULL, data TEXT NOT NULL)""",
                ):
                    db.execute(statement)
                db.execute("PRAGMA user_version=1")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def event(db, experiment, kind, data):
        db.execute(
            "INSERT INTO events(timestamp,experiment,type,data) VALUES(?,?,?,?)",
            (time.time(), experiment, kind, json.dumps(data, allow_nan=False)),
        )
        db.execute("DELETE FROM events WHERE seq <= (SELECT MAX(seq)-512 FROM events)")

    def events(self, after=0):
        with self.connect() as db:
            return [
                {**dict(row), "data": json.loads(row["data"])}
                for row in db.execute(
                    "SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT 512", (after,)
                )
            ]

    def sync_metrics(self, experiment, history):
        with self.connect() as db:
            db.execute("DELETE FROM metrics WHERE experiment=?", (experiment,))
            db.executemany(
                "INSERT INTO metrics(experiment,generation,data) VALUES(?,?,?)",
                [(experiment, r["generation"], json.dumps(r)) for r in history],
            )
            db.execute(
                "UPDATE workers SET generation=? WHERE experiment=?", (len(history), experiment)
            )
            self.event(db, experiment, "generation", {"generation": len(history)})
