"""Bounded cross-process telemetry. Nonblocking writes drop under backpressure."""

import json
import sqlite3
import time
import uuid
import weakref
from pathlib import Path

from evoforge.games import frame, metric


class FrameChannel:
    capacity = 256
    max_bytes = 65536

    def __init__(self, directory):
        self.path = Path(directory) / "telemetry.sqlite"
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS frames (seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)"
            )

    def publish(self, payload):
        raw = json.dumps(payload, allow_nan=False)
        if len(raw.encode()) > self.max_bytes:
            return False
        db = sqlite3.connect(self.path, timeout=0)
        try:
            with db:
                db.execute("INSERT INTO frames(data) VALUES(?)", (raw,))
                db.execute(
                    "DELETE FROM frames WHERE seq <= (SELECT MAX(seq)-? FROM frames)",
                    (self.capacity,),
                )
            return True
        except sqlite3.OperationalError:
            return False
        finally:
            db.close()

    def read(self, after=0):
        return self.read_existing(self.path.parent, after)

    @classmethod
    def read_existing(cls, directory, after=0):
        """Read a persisted ring without creating a database or changing its schema.

        Spectators must not run writer initialization on every poll. Missing or
        unreadable storage raises a SQLite error for the client to report.
        """
        path = (Path(directory) / "telemetry.sqlite").resolve()
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.1) as db:
            rows = db.execute(
                "SELECT seq,data FROM frames WHERE seq>? ORDER BY seq LIMIT ?",
                (after, cls.capacity),
            ).fetchall()
        return [{"seq": seq, **json.loads(raw)} for seq, raw in rows]


class TrainingPublisher:
    def __init__(self, directory, game, worker_identity=None, sample_interval=0.04):
        self.channel = FrameChannel(directory)
        self.experiment = Path(directory).name
        self.game = game
        self.worker_identity = worker_identity
        self.last = 0.0
        self.sample_interval = sample_interval
        self.episodes = weakref.WeakKeyDictionary()
        self.dropped = 0

    def __call__(self, env, episode, reward, terminated, truncated, generation, agent, phase):
        # Sample evaluation frames; PPO rollouts are not spectator episodes.
        if phase not in ("training", "validation") or agent >= 3:
            return
        now = time.monotonic()
        if env.steps == 1 or env not in self.episodes:
            self.episodes[env] = uuid.uuid4().hex
        if now - self.last < self.sample_interval and not (terminated or truncated):
            return
        self.last = now
        payload = {
            "experiment": self.experiment,
            "worker": self.worker_identity,
            "game": self.game,
            "generation": generation,
            "agent": str(agent),
            "episode": self.episodes[env],
            "episode_index": episode,
            "timestamp": time.time(),
            "step": env.steps,
            "score": metric(env),
            "reward": float(reward),
            "terminated": bool(terminated),
            "truncated": bool(truncated),
            "phase": phase,
            "data": frame(env),
            "dropped": self.dropped,
        }
        if not self.channel.publish(payload):
            self.dropped += 1
