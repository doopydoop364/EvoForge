"""Per-experiment research data. Checkpoints remain the training authority.

Node identities describe occurrences (generation/slot), while fingerprints describe
parameter content. Old ancestry is never guessed. Retained weights have an explicit
byte budget; historical metadata and observations survive weight eviction.
"""

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np

SCHEMA = 2
DEFAULT_WEIGHT_BYTES = 64 * 1024 * 1024


SCHEMA_SQL = """
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY, generation INTEGER NOT NULL, slot INTEGER NOT NULL,
                    operation TEXT NOT NULL, parents TEXT NOT NULL, fingerprint TEXT,
                    descriptor TEXT, weights BLOB, fitness REAL);
                CREATE INDEX IF NOT EXISTS node_generation ON nodes(generation, slot);
                CREATE TABLE IF NOT EXISTS history (generation INTEGER PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bookmarks (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, view TEXT NOT NULL,
                    generation INTEGER, agent TEXT, notes TEXT NOT NULL, created REAL NOT NULL, right_agent TEXT);

            """


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def pack_state(state, architecture):
    layout, parts, offset = [], [], 0
    for name, tensor in sorted(state.items()):
        values = tensor.detach().cpu().numpy().astype("<f4", copy=False)
        if not np.isfinite(values).all():
            raise ValueError("Non-finite model parameters")
        layout.append(
            {"name": name, "shape": list(values.shape), "offset": offset, "count": values.size}
        )
        parts.append(values.tobytes())
        offset += values.size
    raw = b"".join(parts)
    descriptor = encoded({"architecture": architecture, "layout": layout})
    digest = hashlib.sha256(descriptor.encode() + b"\0" + raw).hexdigest()
    return descriptor, raw, digest


class ResearchStore:
    def __init__(self, directory):
        self.path = Path(directory) / "research.sqlite"
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA:
                raise ValueError("Unsupported research database version")
            db.executescript(SCHEMA_SQL)
            db.execute("BEGIN IMMEDIATE")
            columns = {r[1] for r in db.execute("PRAGMA table_info(bookmarks)")}
            if "right_agent" not in columns:
                db.execute("ALTER TABLE bookmarks ADD COLUMN right_agent TEXT")
            db.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA trusted_schema=OFF")
        try:
            with db:
                yield db
        finally:
            db.close()

    def metadata(self):
        with self.connect() as db:
            values = {
                r["key"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM metadata")
            }
        return {"notes": "", "tags": [], "weight_bytes": DEFAULT_WEIGHT_BYTES, **values}

    def annotate(self, notes, tags):
        with self.connect() as db:
            for key, value in (("notes", notes), ("tags", sorted(set(tags)))):
                db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, encoded(value)))
        return self.metadata()

    def sync(self, checkpoint):
        generation = int(checkpoint["generation"])
        config = checkpoint["config"]
        population = checkpoint["population"]
        ancestry = {(r["generation"], r["agent"]): r for r in checkpoint.get("lineage", [])}
        history = {int(r["generation"]): r for r in checkpoint.get("history", [])}
        metadata = self.metadata()
        cap = metadata["weight_bytes"]
        previous = metadata.get("indexed_generation", -1)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Recovery must not leave observations from a discarded future commit.
            db.execute("DELETE FROM nodes WHERE generation>?", (generation,))
            db.execute("UPDATE nodes SET fitness=NULL WHERE generation>=?", (generation,))
            db.execute("DELETE FROM history WHERE generation>=?", (generation,))
            for g, row in history.items():
                if g >= generation or (previous < generation and g < previous):
                    continue
                db.execute("INSERT OR REPLACE INTO history VALUES (?,?)", (g, encoded(row)))
                scores = row.get("population_fitness", "[]")
                scores = json.loads(scores) if isinstance(scores, str) else scores
                for i, score in enumerate(scores):
                    self._node(db, g, i, ancestry, config)
                    db.execute("UPDATE nodes SET fitness=? WHERE id=?", (score, f"{g}:{i}"))
            for i, state in enumerate(population):
                self._node(db, generation, i, ancestry, config)
                descriptor, raw, digest = pack_state(state, checkpoint["architecture"])
                db.execute(
                    "UPDATE nodes SET fingerprint=?, descriptor=?, weights=? WHERE id=?",
                    (digest, descriptor, raw if len(raw) <= cap else None, f"{generation}:{i}"),
                )
            used = db.execute("SELECT COALESCE(SUM(LENGTH(weights)),0) FROM nodes").fetchone()[0]
            # Keep the newest available weights; don't promise unavailable history.
            for row in db.execute(
                "SELECT id,LENGTH(weights) AS n FROM nodes WHERE weights IS NOT NULL ORDER BY generation,slot"
            ).fetchall():
                if used <= cap:
                    break
                db.execute("UPDATE nodes SET weights=NULL WHERE id=?", (row["id"],))
                used -= row["n"]
            for key, value in (
                ("indexed_generation", generation),
                ("indexed_at", time.time()),
                (
                    "manifest",
                    checkpoint.get("research_manifest", {"provenance": "legacy; incomplete"}),
                ),
                ("champions", checkpoint.get("champion_history", [])),
            ):
                db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, encoded(value)))

    @staticmethod
    def _node(db, g, i, ancestry, config):
        row = ancestry.get((g, i))
        if row:
            parents = [f"{g - 1}:{p}" for p in row["parents"]]
            operation = row["operation"]
        else:
            parents, operation = [], "initial" if g == 0 else "unrecorded"
        db.execute(
            "INSERT INTO nodes(id,generation,slot,operation,parents) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET operation=excluded.operation,parents=excluded.parents",
            (f"{g}:{i}", g, i, operation, encoded(parents)),
        )

    def family(self, generation=None, offset=0, limit=200):
        meta = self.metadata()
        g = meta.get("indexed_generation", 0) if generation is None else generation
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,generation,slot,operation,parents,fingerprint,fitness,weights IS NOT NULL AS weights_available FROM nodes WHERE generation BETWEEN ? AND ? ORDER BY generation,slot LIMIT ? OFFSET ?",
                (max(0, g - 2), g, limit, offset),
            ).fetchall()
            count = db.execute(
                "SELECT COUNT(*) FROM nodes WHERE generation BETWEEN ? AND ?", (max(0, g - 2), g)
            ).fetchone()[0]
        return {
            "generation": g,
            "total": count,
            "offset": offset,
            "limit": limit,
            "indexed_generation": meta.get("indexed_generation"),
            "nodes": [
                {
                    **dict(r),
                    "parents": json.loads(r["parents"]),
                    "weights_available": bool(r["weights_available"]),
                    "fitness": r["fitness"] if r["generation"] < g else None,
                }
                for r in rows
            ],
        }

    def history(self, start=0, end=1000000, limit=300):
        with self.connect() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM history WHERE generation BETWEEN ? AND ?", (start, end)
            ).fetchone()[0]
            # SQL selects bounded uniformly spaced rows, plus endpoints. No unbounded JSON decode.
            stride = max(1, (total + max(1, limit - 2) - 1) // max(1, limit - 2))
            rows = db.execute(
                "SELECT data FROM (SELECT generation,data,ROW_NUMBER() OVER (ORDER BY generation)-1 AS n FROM history WHERE generation BETWEEN ? AND ?) WHERE n % ? = 0 OR n = ? ORDER BY generation LIMIT ?",
                (start, end, stride, total - 1, limit),
            ).fetchall()
        return {
            "rows": [json.loads(r[0]) for r in rows],
            "total": total,
            "sampled": total > len(rows),
            "sampling": "uniform committed generations; endpoints retained",
        }

    def generation(self, generation):
        with self.connect() as db:
            row = db.execute(
                "SELECT data FROM history WHERE generation=?", (generation,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def weights(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM nodes WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        if row["weights"] is None:
            raise ValueError("Weights were not recorded or have been removed by retention")
        descriptor = json.loads(row["descriptor"])
        raw = row["weights"]
        digest = hashlib.sha256(row["descriptor"].encode() + b"\0" + raw).hexdigest()
        if digest != row["fingerprint"]:
            raise ValueError("Research weights fingerprint mismatch")
        values = np.frombuffer(raw, dtype="<f4")
        if not np.isfinite(values).all():
            raise ValueError("Non-finite research weights")
        return descriptor, values, dict(row)

    def bookmarks(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute("SELECT * FROM bookmarks ORDER BY created DESC LIMIT 500")
            ]

    def bookmark(self, title, view, generation=None, agent=None, notes="", right_agent=None):
        with self.connect() as db:
            if db.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0] >= 500:
                raise ValueError("Bookmark limit reached (500 per experiment)")
            identifier = uuid.uuid4().hex
            db.execute(
                "INSERT INTO bookmarks(id,title,view,generation,agent,notes,created,right_agent) VALUES(?,?,?,?,?,?,?,?)",
                (identifier, title, view, generation, agent, notes, time.time(), right_agent),
            )
        return {"id": identifier}

    def delete_bookmark(self, identifier):
        with self.connect() as db:
            if not db.execute("DELETE FROM bookmarks WHERE id=?", (identifier,)).rowcount:
                raise KeyError(identifier)

    def retain(self, weight_bytes):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO metadata VALUES('weight_bytes',?)", (encoded(weight_bytes),)
            )
            used = db.execute("SELECT COALESCE(SUM(LENGTH(weights)),0) FROM nodes").fetchone()[0]
            for row in db.execute(
                "SELECT id,LENGTH(weights) AS n FROM nodes WHERE weights IS NOT NULL ORDER BY generation,slot"
            ).fetchall():
                if used <= weight_bytes:
                    break
                db.execute("UPDATE nodes SET weights=NULL WHERE id=?", (row["id"],))
                used -= row["n"]
        # Release pages without altering authoritative checkpoints or historical metadata.
        with self.connect() as db:
            db.execute("VACUUM")
        return {"retained_weight_bytes": used, "budget": weight_bytes}
