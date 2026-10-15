"""Versioned sampled episodes with bounded asynchronous persistence."""

import json
import os
import queue
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from evoforge.core.checkpoints import atomic_bytes
from evoforge.games import game_version
from evoforge.rendering.schema import Model, Scene

MAX_FRAMES = 2048
MAX_RECORDING_BYTES = 8 * 1024 * 1024


class RecordedFrame(Model):
    seq: int = Field(ge=0)
    timestamp: float = Field(ge=0)
    step: int = Field(ge=0)
    score: float
    reward: float
    terminated: bool = False
    truncated: bool = False
    scene: Scene | None = None
    text: str = Field("", max_length=65536)


class Recording(Model):
    format_version: Literal[1] = 1
    renderer_protocol: Literal[1] = 1
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    run: str = Field(max_length=80)
    game: str = Field(max_length=80)
    game_version: str = Field(max_length=80)
    agent: str = Field(max_length=80)
    seed: int | None = None
    generation: int = 0
    episode: str = Field(max_length=80)
    source: Literal["training", "validation", "champion", "population"]
    created: float
    complete: bool = False
    sampled: bool = True
    dropped: int = Field(0, ge=0)
    frames: list[RecordedFrame] = Field(min_length=1, max_length=MAX_FRAMES)

    @model_validator(mode="after")
    def ordered(self):
        if any(
            a.seq >= b.seq or a.timestamp > b.timestamp or a.step >= b.step
            for a, b in zip(self.frames, self.frames[1:])
        ):
            raise ValueError(
                "Replay frames must have strictly increasing sequence/steps and ordered timestamps"
            )
        return self


class ReplayStore:
    def __init__(self, directory):
        self.path = Path(directory) / "replays"
        self.max_bytes = max(1024, int(os.environ.get("EVOFORGE_REPLAY_BYTES", 64 * 1024 * 1024)))
        self.max_episodes = max(1, int(os.environ.get("EVOFORGE_REPLAY_EPISODES", 100)))

    def save(self, recording):
        import fcntl

        item = Recording.model_validate(recording)
        raw = item.model_dump_json().encode()
        if len(raw) > min(MAX_RECORDING_BYTES, self.max_bytes):
            raise ValueError("Recording exceeds storage limit")
        self.path.mkdir(exist_ok=True)
        with (self.path / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            atomic_bytes(self.path / f"{item.id}.json", raw)
            files = sorted(self.path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            total = 0
            for i, path in enumerate(files):
                total += path.stat().st_size
                if i >= self.max_episodes or total > self.max_bytes:
                    path.unlink()
        return self.metadata(item)

    @staticmethod
    def metadata(item):
        data = item.model_dump(exclude={"frames"})
        data.update(
            frame_count=len(item.frames),
            duration=max(0, item.frames[-1].timestamp - item.frames[0].timestamp),
            score=item.frames[-1].score,
            observed_reward_sum=sum(frame.reward for frame in item.frames),
        )
        return data

    def get(self, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise KeyError(identifier)
        path = self.path / f"{identifier}.json"
        if path.is_symlink() or not path.is_file():
            raise KeyError(identifier)
        if path.stat().st_size > MAX_RECORDING_BYTES:
            raise ValueError("Recording exceeds 8 MiB")
        return Recording.model_validate_json(path.read_bytes())

    def list(self):
        result = []
        for path in self.path.glob("*.json"):
            try:
                result.append(self.metadata(self.get(path.stem)))
            except (ValueError, KeyError, OSError):
                continue
        return sorted(result, key=lambda x: x["created"], reverse=True)[: self.max_episodes]


def recording_frame(payload, seq):
    return {
        "seq": seq,
        "timestamp": payload["timestamp"],
        "step": payload["step"],
        "score": payload["score"],
        "reward": payload["reward"],
        "terminated": payload["terminated"],
        "truncated": payload["truncated"],
        "scene": payload["data"].get("scene"),
        "text": payload["data"].get("text", "")[:65536],
    }


class EpisodeRecorder:
    """Training never waits for disk; a full queue drops presentation frames."""

    def __init__(self, directory, game):
        self.store = ReplayStore(directory)
        self.run, self.game = Path(directory).name, game
        self.version = game_version(game)
        self.queue = queue.Queue(maxsize=128)
        self.done = threading.Event()
        self.dropped = 0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, payload):
        try:
            self.queue.put_nowait(payload)
        except queue.Full:
            self.dropped += 1

    def _run(self):
        episodes = {}
        sequence = 0
        while not self.done.is_set() or not self.queue.empty():
            try:
                payload = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            sequence += 1
            key = payload["episode"]
            if key not in episodes:
                if len(episodes) >= 12:
                    _, old = episodes.popitem()
                    self._save(old)
                episodes[key] = {
                    "id": uuid.uuid4().hex,
                    "run": self.run,
                    "game": self.game,
                    "game_version": self.version,
                    "agent": payload["agent"],
                    "seed": payload.get("seed"),
                    "generation": payload["generation"],
                    "episode": key,
                    "source": payload["phase"],
                    "created": payload["timestamp"],
                    "frames": [],
                    "complete": False,
                    "dropped": 0,
                }
            item = episodes[key]
            size = len(json.dumps(payload, allow_nan=False).encode())
            if len(item["frames"]) < MAX_FRAMES and item.get("_bytes", 0) + size <= 4 * 1024 * 1024:
                item["frames"].append(recording_frame(payload, sequence))
                item["_bytes"] = item.get("_bytes", 0) + size
            else:
                item["dropped"] += 1
            if payload["terminated"] or payload["truncated"]:
                item["complete"] = item["dropped"] == 0 and self.dropped == 0
                self._save(episodes.pop(key))
        for item in episodes.values():
            self._save(item)

    def _save(self, item):
        try:
            item.pop("_bytes", None)
            item["dropped"] += self.dropped
            self.store.save(item)
        except (ValueError, OSError):
            self.dropped += len(item["frames"])

    def close(self):
        self.done.set()
        self.thread.join(timeout=5)


def generate_replays(directory, mode, seed, limit):
    """One bounded episode per selected agent; model execution stays on server."""
    from evoforge.games import metric
    from evoforge.telemetry.spectator import Replay

    replay = Replay(directory, mode=mode, seed=seed, limit=limit)
    store = ReplayStore(directory)
    records = []
    cfg = json.loads((Path(directory) / "config.json").read_text())
    game = cfg.get("game", "snake")
    try:
        for i, agent in enumerate(replay.agents):
            from evoforge.games import frame, transition

            env = agent["env"]
            rows = []
            total_bytes = 0
            started = time.monotonic()
            for step in range(min(cfg["max_steps"], MAX_FRAMES)):
                obs, reward, terminal, truncated, _ = transition(
                    env, agent["policy"].act(agent["obs"], deterministic=True)
                )
                agent["obs"] = obs
                row = recording_frame(
                    {
                        "timestamp": step / 20,
                        "step": step + 1,
                        "score": metric(env),
                        "reward": reward,
                        "terminated": terminal,
                        "truncated": truncated,
                        "data": frame(env),
                    },
                    step,
                )

                size = len(json.dumps(row, allow_nan=False).encode())
                if total_bytes + size > min(4 * 1024 * 1024, max(0, store.max_bytes - 2048)):
                    break
                rows.append(row)
                total_bytes += size
                if terminal or truncated or time.monotonic() - started > 10:
                    break
            records.append(
                store.save(
                    {
                        "id": uuid.uuid4().hex,
                        "run": Path(directory).name,
                        "game": game,
                        "game_version": game_version(game),
                        "agent": str(i),
                        "seed": seed + i,
                        "episode": uuid.uuid4().hex,
                        "source": mode,
                        "created": time.time(),
                        "complete": bool(
                            rows and (rows[-1]["terminated"] or rows[-1]["truncated"])
                        ),
                        "sampled": False,
                        "frames": rows,
                    }
                )
            )
    finally:
        replay.close()
    return records
