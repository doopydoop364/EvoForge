"""Actual TCP HTTP/WebSocket server, separate from in-process API tests."""

import json
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from websockets.sync.client import connect

from evoforge.supervisor import Supervisor

pytestmark = pytest.mark.integration


def test_real_http_websocket_transport_and_supervisor(tmp_path):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    token = "owned-network-test-token"
    headers = {"Authorization": f"Bearer {token}"}
    root = tmp_path / "runs"
    with (tmp_path / "server.log").open("w") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "evoforge.cli",
                "api",
                "serve",
                "--root",
                str(root),
                "--port",
                str(port),
            ],
            env={**os.environ, "EVOFORGE_API_TOKEN": token},
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    manager = None
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10
        ) as client:
            deadline = time.monotonic() + 20
            while True:
                try:
                    assert client.get("/api/v1/games").status_code == 401
                    break
                except httpx.ConnectError:
                    assert time.monotonic() < deadline
                    time.sleep(0.05)
            assert client.get("/api/v1/games", headers=headers).status_code == 200
            payload = {
                "id": "transport",
                "config": {
                    "game": "coin",
                    "mode": "evolution",
                    "population": 2,
                    "elites": 1,
                    "ppo_candidates": 0,
                    "generations": 1,
                    "eval_episodes": 1,
                    "hidden": 8,
                },
            }
            assert (
                client.post("/api/v1/experiments", json=payload, headers=headers).status_code == 201
            )
            assert (
                client.post("/api/v1/experiments/transport/start", headers=headers).status_code
                == 200
            )
            manager = Supervisor(root)
            deadline = time.monotonic() + 20
            while manager.inspect("transport")["status"] != "COMPLETED":
                assert manager.inspect("transport")["status"] != "FAILED"
                assert time.monotonic() < deadline
                time.sleep(0.05)
            with connect(
                f"ws://127.0.0.1:{port}/api/v1/experiments/transport/spectator",
                additional_headers=headers,
                proxy=None,
            ) as ws:
                batch = json.loads(ws.recv(timeout=5))
                assert batch["frames"] and "Coin:" in batch["frames"][0]["data"]["text"]
            assert (
                client.get("/api/v1/experiments/transport/champion", headers=headers).status_code
                == 200
            )
    finally:
        if manager and manager.inspect("transport")["status"] in ("STARTING", "RUNNING", "PAUSED"):
            manager.request("transport", "stop")
        server.terminate()
        server.wait(timeout=10)
