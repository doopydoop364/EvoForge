"""Disposable real server for browser acceptance tests. Never uses production runs."""

import os
import tempfile
import time
from pathlib import Path

import uvicorn

from evoforge.api.app import create_app
from evoforge.supervisor.lifecycle import ACTIVE
from evoforge.telemetry import FrameChannel

# CI installs the backend wheel; its package directory does not contain web/dist.
# Select the frontend built by this checkout explicitly, as production wheel users do.
os.environ.setdefault("EVOFORGE_WEB_DIR", str(Path(__file__).resolve().parents[1] / "web" / "dist"))

with tempfile.TemporaryDirectory(prefix="evoforge-web-e2e-") as directory:
    app = create_app(directory, token="browser-test-token")
    # A pre-existing terminal-only run reproduces the saved-frame regression
    # without starting a worker or touching the operator's experiment root.
    app.state.supervisor.create("saved-geometry-text", {"game": "geometrydash"})
    FrameChannel(Path(directory) / "saved-geometry-text").publish(
        {
            "experiment": "saved-geometry-text",
            "game": "geometrydash",
            "agent": "0",
            "worker": "fixture",
            "generation": 199,
            "episode": "captured",
            "episode_index": 2,
            "timestamp": time.time() - 3600,
            "step": 28,
            "score": 27,
            "reward": -1.0,
            "terminated": True,
            "truncated": False,
            "data": {"text": "--X-------\n" + "          \n" * 7 + ".....^....\n##########"},
        }
    )
    try:
        uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("EVOFORGE_TEST_PORT", "8766")))
    finally:
        manager = app.state.supervisor
        for run in manager.list():
            if run["status"] in ACTIVE:
                try:
                    manager.request(run["id"], "stop")
                except ValueError:
                    pass
        deadline = time.monotonic() + 10
        while (
            any(run["status"] in ACTIVE for run in manager.list()) and time.monotonic() < deadline
        ):
            time.sleep(0.1)
