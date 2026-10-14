"""Stable, UI-independent run and analytics service for local or web frontends."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path


def read_metrics(directory):
    path = Path(directory) / "metrics.csv"
    if not path.exists():
        return []
    with path.open(newline="") as stream:
        return [{k: _coerce(v) for k, v in row.items()} for row in csv.DictReader(stream)]


def _coerce(value):
    try:
        return float(value) if "." in value else int(value)
    except (ValueError, TypeError):
        return value


def summarize(rows):
    if not rows:
        return {"generations": 0, "latest": None, "best": None, "trend": None}
    values = [float(row["best_train"]) for row in rows if row.get("best_train") not in (None, "")]
    trend = None if len(values) < 2 else round(values[-1] - values[0], 6)
    return {"generations": len(rows), "latest": rows[-1], "best": max(values) if values else None, "trend": trend}


class RunService:
    """Read-only snapshot interface shared by the TUI and future frontends."""
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()

    def snapshot(self):
        def read_json(name):
            try:
                return json.loads((self.directory / name).read_text())
            except (OSError, ValueError):
                return {}
        metrics = read_metrics(self.directory)
        cfg = read_json("config.json")
        worker = read_json("worker.json")
        if worker.get("state") == "running":
            try:
                os.kill(int(worker["pid"]), 0)
            except (OSError, KeyError, TypeError, ValueError):
                worker = {**worker, "state": "stale"}
        return {"run": self.directory.name, "path": str(self.directory), "config": cfg,
                "metrics": summarize(metrics), "worker": worker,
                "checkpoint": (self.directory / "checkpoint.pt").exists(),
                "checkpoint_backup": (self.directory / "checkpoint.pt.bak").exists(),
                "champion": (self.directory / "champion.pt").exists(),
                "spectator": (self.directory / "spectator.pt").exists()}
