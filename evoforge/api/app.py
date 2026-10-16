"""Versioned local API. All experiment mutations use the shared supervisor."""

import asyncio
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from evoforge import __version__
from evoforge.core.experiments import compare, export_metrics
from evoforge.games import available_games, game_spec, game_version
from evoforge.service import read_metrics
from evoforge.supervisor import Supervisor, WorkerConflict

from .schemas import Experiment, ExperimentCreate, Game, NamedAction, TrainingConfig

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def create_app(root="runs", token=None, bind_host="127.0.0.1"):
    token = token if token is not None else os.environ.get("EVOFORGE_API_TOKEN")
    if bind_host not in LOCAL_HOSTS and not token:
        raise ValueError("Remote binding requires EVOFORGE_API_TOKEN")
    manager = Supervisor(root)
    security = HTTPBearer(auto_error=False)

    session_key = secrets.token_bytes(32)
    allowed_origins = set(filter(None, os.environ.get("EVOFORGE_ALLOWED_ORIGINS", "").split(",")))

    def origin_allowed(connection):
        origin = connection.headers.get("origin")
        if not origin:
            return True
        parsed = urlsplit(origin)
        return origin in allowed_origins or (
            parsed.scheme in {"http", "https"} and parsed.netloc == connection.headers.get("host")
        )

    def valid_cookie(connection):
        value = connection.cookies.get("evoforge_session", "")
        try:
            expiry, signature = value.split(".")
            expected = hmac.new(session_key, expiry.encode(), hashlib.sha256).hexdigest()
            return int(expiry) > time.time() and hmac.compare_digest(signature, expected)
        except (ValueError, TypeError):
            return False

    def authenticated(
        request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(security)
    ):
        if not origin_allowed(request):
            raise HTTPException(403, "Origin not allowed")
        if token and valid_cookie(request):
            return
        if token and (
            not credentials
            or credentials.scheme.lower() != "bearer"
            or not hmac.compare_digest(credentials.credentials, token)
        ):
            raise HTTPException(
                401, "Valid Bearer token required", headers={"WWW-Authenticate": "Bearer"}
            )

    app = FastAPI(title="EvoForge API", version=__version__)
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    from .web import RequestLimits

    app.add_middleware(RequestLimits)
    hosts = list(
        LOCAL_HOSTS
        | {"testserver"}
        | set(filter(None, os.environ.get("EVOFORGE_ALLOWED_HOSTS", "").split(",")))
    )
    if "*" in hosts or "*" in allowed_origins:
        raise ValueError("Wildcard browser hosts/origins are not supported")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    router = APIRouter(dependencies=[Depends(authenticated)])
    app.state.supervisor = manager

    @app.exception_handler(KeyError)
    async def missing(_, exc):
        return JSONResponse(status_code=404, content={"detail": "Experiment or game not found"})

    @app.exception_handler(WorkerConflict)
    async def conflict(_, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(TypeError)
    async def invalid_type(_, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def describe(game):
        spec = game_spec(game)
        return Game(
            id=spec.id,
            name=spec.title,
            version=game_version(game),
            observation_size=spec.observation_size,
            action_size=spec.action_size,
            score_name=spec.score_label,
        )

    @router.get("/api/v1/games", response_model=list[Game])
    def games():
        return [describe(name) for name in available_games()]

    @router.get("/api/v1/games/{game_id}", response_model=Game)
    def game(game_id: str):
        if game_id not in available_games():
            raise HTTPException(404, "Game not found")
        return describe(game_id)

    @router.get("/api/v1/experiments", response_model=list[Experiment])
    def experiments():
        return manager.list()

    @router.post("/api/v1/experiments", response_model=Experiment, status_code=201)
    def create(request: ExperimentCreate):
        return manager.create(request.id, request.config.model_dump())

    @router.get("/api/v1/experiments/{experiment}", response_model=Experiment)
    def inspect(experiment: str):
        return manager.inspect(experiment)

    @router.put("/api/v1/experiments/{experiment}", response_model=Experiment)
    def update(experiment: str, config: TrainingConfig):
        return manager.update(experiment, config.model_dump())

    @router.delete("/api/v1/experiments/{experiment}", response_model=Experiment)
    def archive(experiment: str):
        return manager.archive(experiment)

    @router.post("/api/v1/experiments/{experiment}/unarchive", response_model=Experiment)
    def unarchive(experiment: str):
        return manager.archive(experiment, False)

    @router.post(
        "/api/v1/experiments/{experiment}/duplicate", response_model=Experiment, status_code=201
    )
    def duplicate(experiment: str, request: NamedAction):
        return manager.duplicate(experiment, request.destination)

    @router.post("/api/v1/experiments/{experiment}/rename", response_model=Experiment)
    def rename(experiment: str, request: NamedAction):
        return manager.rename(experiment, request.destination)

    @router.post("/api/v1/experiments/{experiment}/start", response_model=Experiment)
    def start(experiment: str):
        manager.inspect(experiment)
        return manager.start(experiment)

    for action in ("pause", "resume", "stop"):

        def endpoint(name):
            def control(experiment: str):
                return manager.request(experiment, name)

            control.__name__ = name
            return control

        router.add_api_route(
            f"/api/v1/experiments/{{experiment}}/{action}",
            endpoint(action),
            methods=["POST"],
            response_model=Experiment,
        )

    @router.get("/api/v1/experiments/{experiment}/metrics", response_model=list[dict])
    def metrics(experiment: str):
        manager.inspect(experiment)
        return read_metrics(manager.path(experiment))

    @router.get("/api/v1/experiments/{experiment}/export")
    def export(experiment: str, format: Literal["json", "csv"] = "json"):
        manager.inspect(experiment)
        return Response(
            export_metrics(manager.path(experiment), format),
            media_type="application/json" if format == "json" else "text/csv",
        )

    @router.get("/api/v1/compare")
    def comparison(experiments: str, budget: int | None = Query(None, ge=1)):
        return compare(manager, experiments.split(","), budget)

    @router.get("/api/v1/experiments/{experiment}/agents")
    def agents(experiment: str):
        from evoforge.core.checkpoints import load_recovering

        manager.inspect(experiment)
        path = manager.path(experiment) / "checkpoint.pt"
        if not path.exists():
            return {"agents": [], "champions": [], "lineage": []}
        data, recovered = load_recovering(path)
        return {
            "agents": [
                {"id": str(i), "architecture": data.get("architecture")}
                for i in range(len(data["population"]))
            ],
            "champions": data.get("champion_history", []),
            "lineage": data.get("lineage", []),
            "backup": recovered,
        }

    @router.get("/api/v1/experiments/{experiment}/champion")
    def champion(experiment: str):
        manager.inspect(experiment)
        path = manager.path(experiment) / "champion.pt"
        if not path.is_file():
            raise HTTPException(404, "Champion not yet available")
        return FileResponse(
            path, filename=f"{experiment}-champion.pt", media_type="application/octet-stream"
        )

    @router.get("/api/v1/workers", response_model=list[Experiment])
    def workers():
        return manager.workers()

    @router.post("/api/v1/session")
    def session(request: Request):
        expiry = str(int(time.time()) + 8 * 3600)
        signature = hmac.new(session_key, expiry.encode(), hashlib.sha256).hexdigest()
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            "evoforge_session",
            f"{expiry}.{signature}",
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            max_age=8 * 3600,
            path="/api",
        )
        return response

    @router.delete("/api/v1/session")
    def logout():
        response = JSONResponse({"authenticated": False})
        response.delete_cookie("evoforge_session", path="/api")
        return response

    from .web import install_routes

    install_routes(router, manager)
    from .research import install_routes as install_research

    install_research(router, manager)
    app.include_router(router)

    async def stream(websocket, experiment, since):
        if not origin_allowed(websocket):
            await websocket.close(code=4403)
            return
        if token and not valid_cookie(websocket):
            header = websocket.headers.get("authorization", "")
            if not hmac.compare_digest(header, f"Bearer {token}"):
                await websocket.close(code=4401)
                return
        if experiment:
            try:
                manager.inspect(experiment)
            except (KeyError, ValueError):
                await websocket.close(code=4404)
                return
        await websocket.accept()
        cursor = since
        try:
            while True:
                if experiment:
                    from evoforge.telemetry import FrameChannel

                    path = manager.path(experiment)
                    frames = await asyncio.to_thread(
                        lambda path=path, after=cursor: (
                            FrameChannel.read_existing(path, after)
                            if (path / "telemetry.sqlite").exists()
                            else []
                        )
                    )
                    # A rename moves the persisted ring intact. Route identity is
                    # authoritative; retain the original name as provenance.
                    frames = [
                        {**f, "recorded_experiment": f.get("experiment"), "experiment": experiment}
                        for f in frames
                    ]
                    key = "frames"
                else:
                    frames = await asyncio.to_thread(manager.database.events, cursor)
                    key = "events"
                gap = bool(frames and frames[0]["seq"] > cursor + 1)
                if frames:
                    cursor = frames[-1]["seq"]
                await websocket.send_json({key: frames, "cursor": cursor, "gap": gap})
                # Also receive disconnect/ping instead of leaving orphan send loops.
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.2)
                except asyncio.TimeoutError:
                    pass
        except (WebSocketDisconnect, RuntimeError):
            return

    # Authentication on WS is explicit: HTTPBearer does not accept a WebSocket.
    # Bearer dependencies apply only to HTTP routes through the APIRouter.
    @app.websocket("/api/v1/events", dependencies=[])
    async def events(websocket: WebSocket, since: int = Query(0, ge=0)):
        await stream(websocket, None, since)

    @app.websocket("/api/v1/experiments/{experiment}/spectator", dependencies=[])
    async def spectator(websocket: WebSocket, experiment: str, since: int = Query(0, ge=0)):
        await stream(websocket, experiment, since)

    static_root = Path(
        os.environ.get("EVOFORGE_WEB_DIR", Path(__file__).resolve().parents[2] / "web" / "dist")
    )
    if (static_root / "index.html").is_file():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=static_root, html=True), name="web")

    return app
