"""Browser services layered on the existing authenticated supervisor API."""

import json
import os
import threading
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Query
from fastapi.responses import Response
from pydantic import Field

from evoforge.games import available_games, close_env, frame, make_env
from evoforge.rendering.assets import asset_response, public_manifest
from evoforge.rendering.schema import Model
from evoforge.service import read_metrics
from evoforge.telemetry.recordings import ReplayStore, generate_replays


class ReplayRequest(Model):
    mode: Literal["champion", "population"] = "champion"
    seed: int = Field(900, ge=0, le=2147483647)
    limit: int = Field(4, ge=1, le=9)


def install_routes(router, manager):
    replay_lock = threading.Lock()
    cpu_lock = threading.Lock()
    cpu_previous = None

    @router.get("/api/v1/health")
    def health():
        return {"status": "ok", "renderer_protocol": 1}

    @router.get("/api/v1/dashboard")
    def dashboard():
        nonlocal cpu_previous
        from evoforge.supervisor.lifecycle import ACTIVE

        runs = manager.list()
        latest = {}
        for run in runs:
            history = read_metrics(manager.path(run["id"]))
            latest[run["id"]] = history[-1] if history else None
        resources = {
            "cpu_count": os.cpu_count(),
            "cpu_percent": None,
            "load_average": None,
            "memory_used_bytes": None,
            "memory_total_bytes": None,
            "gpu": {"available": False, "note": "Training uses CPU; GPU utilization unavailable"},
        }
        try:
            resources["load_average"] = list(os.getloadavg())
            memory = {
                line.split(":")[0]: int(line.split()[1]) * 1024
                for line in Path("/proc/meminfo").read_text().splitlines()
            }
            resources["memory_total_bytes"] = memory["MemTotal"]
            resources["memory_used_bytes"] = memory["MemTotal"] - memory["MemAvailable"]
        except (OSError, AttributeError, KeyError, ValueError):
            pass
        try:
            with cpu_lock:
                ticks = [
                    int(n) for n in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]
                ]
                total, idle = sum(ticks), ticks[3] + ticks[4]
                if cpu_previous and total > cpu_previous[0]:
                    resources["cpu_percent"] = round(
                        max(
                            0,
                            min(
                                100,
                                100 * (1 - (idle - cpu_previous[1]) / (total - cpu_previous[0])),
                            ),
                        ),
                        1,
                    )
                cpu_previous = (total, idle)
        except (OSError, ValueError, IndexError):
            pass
        import torch

        resources["gpu"]["available"] = torch.cuda.is_available()
        return {
            "active_workers": sum(r["status"] in ACTIVE for r in runs),
            "experiments": len(runs),
            "latest": latest,
            "resources": resources,
            "activity": manager.database.events()[-20:],
            "warnings": [
                {"experiment": r["id"], "error": r["worker"]["error"]}
                for r in runs
                if r["worker"] and r["worker"].get("error")
            ],
        }

    @router.get("/api/v1/games/{game}/manifest")
    def manifest(game: str):
        return public_manifest(game)

    @router.get("/api/v1/games/{game}/assets/{digest}/{identifier}")
    def asset(game: str, digest: str, identifier: str):
        data, media_type, version = asset_response(game, identifier, digest)
        return Response(
            data,
            media_type=media_type,
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "ETag": f'"{version}"',
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            },
        )

    @router.get("/api/v1/games/{game}/scene")
    def preview(game: str, seed: int = Query(42, ge=0, le=2147483647)):
        if game not in available_games():
            raise KeyError(game)
        env = make_env(game)
        try:
            env.reset(seed)
            return frame(env)
        finally:
            close_env(env)

    @router.get("/api/v1/experiments/{experiment}/checkpoints")
    def checkpoints(experiment: str):
        manager.inspect(experiment)
        path = manager.path(experiment)
        return [
            {
                "name": name,
                "bytes": (path / name).stat().st_size,
                "updated": (path / name).stat().st_mtime,
            }
            for name in ("checkpoint.pt", "checkpoint.pt.bak", "champion.pt", "spectator.pt")
            if (path / name).is_file()
        ]

    @router.get("/api/v1/experiments/{experiment}/logs")
    def logs(experiment: str):
        manager.inspect(experiment)
        path = manager.path(experiment) / "training.log"
        if not path.exists():
            return {"text": "", "truncated": False}
        with path.open("rb") as stream:
            size = path.stat().st_size
            stream.seek(max(0, size - 65536))
            return {
                "text": stream.read(65536).decode("utf-8", errors="replace"),
                "truncated": size > 65536,
            }

    @router.get("/api/v1/experiments/{experiment}/replays")
    def recordings(experiment: str):
        manager.inspect(experiment)
        return ReplayStore(manager.path(experiment)).list()

    @router.get("/api/v1/experiments/{experiment}/replays/{identifier}")
    def replay(
        experiment: str,
        identifier: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(256, ge=1, le=512),
    ):
        manager.inspect(experiment)
        store = ReplayStore(manager.path(experiment))
        item = store.get(identifier)
        return {
            **store.metadata(item),
            "frames": [f.model_dump() for f in item.frames[offset : offset + limit]],
            "offset": offset,
        }

    @router.post("/api/v1/experiments/{experiment}/replays", status_code=201)
    def generate(experiment: str, request: ReplayRequest):
        manager.inspect(experiment)
        if not replay_lock.acquire(blocking=False):
            raise HTTPException(409, "Another replay is being generated; try again shortly")
        try:
            path = manager.path(experiment)
            artifact = path / ("champion.pt" if request.mode == "champion" else "spectator.pt")
            if not artifact.is_file():
                raise HTTPException(404, "Train a generation before generating a replay")
            return generate_replays(path, request.mode, request.seed, request.limit)
        finally:
            replay_lock.release()


class RequestLimits:
    """Bound chunked bodies too; reject nested JSON before schema validation."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        if scope["path"] == "/api/v1/research/backups/import" and scope["method"] == "POST":
            # Authenticated endpoint streams into a bounded temporary file; never buffers a ZIP.
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 65536:
                return await Response("Request exceeds 64 KiB", status_code=413)(
                    scope, receive, send
                )
            if not message.get("more_body"):
                break
        if body:
            try:
                value = json.loads(body)
                stack = [(value, 0)]
                count = 0
                while stack:
                    item, depth = stack.pop()
                    count += 1
                    if depth > 12 or count > 4096:
                        raise ValueError("Request JSON complexity limit exceeded")
                    if isinstance(item, dict):
                        stack.extend((v, depth + 1) for v in item.values())
                    elif isinstance(item, list):
                        stack.extend((v, depth + 1) for v in item)
            except (ValueError, RecursionError):
                return await Response("Invalid or excessively nested JSON", status_code=422)(
                    scope, receive, send
                )
        consumed = False

        async def buffered():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, buffered, send)
