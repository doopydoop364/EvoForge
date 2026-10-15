"""Authenticated research workspace endpoints; no arbitrary source-code loading."""

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from evoforge.core.checkpoints import load_recovering
from evoforge.research.analysis import genetic_comparison
from evoforge.research.archive import (
    MAX_BYTES,
    backup_dir,
    backup_path,
    restore_backup,
    validate_archive,
)
from evoforge.research.jobs import Jobs
from evoforge.research.store import ResearchStore

from .schemas import NamedAction, TrainingConfig


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Annotation(Strict):
    notes: str = Field("", max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class Bookmark(Strict):
    title: str = Field(min_length=1, max_length=160)
    view: Literal[
        "Family Trees", "Genetic Comparison", "Evolution Replay", "Compare Runs", "Spectator"
    ]
    generation: int | None = Field(None, ge=0, le=1000000)
    agent: str | None = Field(None, pattern=r"^\d+:\d+$", max_length=32)
    notes: str = Field("", max_length=4000)
    right_agent: str | None = Field(None, pattern=r"^\d+:\d+$", max_length=32)


class Retention(Strict):
    weight_mib: int = Field(64, ge=0, le=1024)
    remove_replays: bool = False


class JobRequest(Strict):
    protocol: Literal["shared_scenarios", "rps_head_to_head"] = "shared_scenarios"
    kind: Literal["tournament", "behavior", "benchmark", "backup"]
    experiments: list[str] = Field(min_length=1, max_length=8)
    seed: int = Field(700000, ge=0, le=2147483583)
    episodes: int = Field(8, ge=1, le=64)
    agents: list[str] | None = Field(None, min_length=2, max_length=2)


class Batch(Strict):
    prefix: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$")
    seeds: list[int] = Field(min_length=1, max_length=8)
    config: TrainingConfig


def install_routes(router, manager):
    jobs = Jobs(manager)

    def store(experiment):
        manager.inspect(experiment)
        return ResearchStore(manager.path(experiment))

    @router.get("/api/v1/experiments/{experiment}/research")
    def metadata(experiment: str):
        research = store(experiment)
        return {**research.metadata(), "bookmarks": research.bookmarks()}

    @router.put("/api/v1/experiments/{experiment}/research")
    def annotate(experiment: str, request: Annotation):
        if any(not tag.strip() or len(tag) > 40 for tag in request.tags):
            raise ValueError("Tags must contain 1–40 characters")
        return store(experiment).annotate(request.notes, [t.strip() for t in request.tags])

    @router.post("/api/v1/experiments/{experiment}/research/index")
    def index(experiment: str):
        with manager._edit_lock(experiment):
            checkpoint, recovered = load_recovering(manager.path(experiment) / "checkpoint.pt")
            store(experiment).sync(checkpoint)
        return {"indexed": True, "generation": checkpoint["generation"], "recovered": recovered}

    @router.get("/api/v1/experiments/{experiment}/research/family")
    def family(
        experiment: str,
        generation: int | None = Query(None, ge=0, le=1000000),
        offset: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=500),
    ):
        return store(experiment).family(generation, offset, limit)

    @router.get("/api/v1/experiments/{experiment}/research/history")
    def history(
        experiment: str,
        start: int = Query(0, ge=0),
        end: int = Query(1000000, ge=0),
        limit: int = Query(300, ge=3, le=1000),
    ):
        if end < start:
            raise ValueError("End generation must be at least the start generation")
        return store(experiment).history(start, end, limit)

    @router.get("/api/v1/experiments/{experiment}/research/generations/{generation}")
    def generation(experiment: str, generation: int):
        if not 0 <= generation <= 1000000:
            raise ValueError("Invalid generation")
        return {"generation": generation, "measurement": store(experiment).generation(generation)}

    @router.get("/api/v1/experiments/{experiment}/research/genetics")
    def genetics(experiment: str, left: str, right: str):
        return genetic_comparison(store(experiment), left, right)

    @router.post("/api/v1/experiments/{experiment}/research/bookmarks", status_code=201)
    def bookmark(experiment: str, request: Bookmark):
        return store(experiment).bookmark(**request.model_dump())

    @router.delete("/api/v1/experiments/{experiment}/research/bookmarks/{identifier}")
    def remove_bookmark(experiment: str, identifier: str):
        store(experiment).delete_bookmark(identifier)
        return {"removed": True}

    @router.post("/api/v1/research/batches", status_code=201)
    def batch(request: Batch):
        from evoforge.trainer import Config

        if len(set(request.seeds)) != len(request.seeds) or any(
            s < 0 or s > 2147483647 for s in request.seeds
        ):
            raise ValueError("Use unique seeds between 0 and 2147483647")
        configs = [{**request.config.model_dump(), "seed": seed} for seed in request.seeds]
        names = [f"{request.prefix}-{seed}" for seed in request.seeds]
        for name, config in zip(names, configs):
            Config(**config).validate()
            if manager.path(name).exists():
                raise ValueError(f"Experiment already exists: {name}")
        import time

        from evoforge.core.checkpoints import atomic_json
        from evoforge.games import game_version

        owned = []
        try:
            # Reserve all destinations before publishing any metadata. A competing
            # request cannot make us remove a directory that it owns.
            for name in names:
                path = manager.path(name)
                path.mkdir()
                owned.append(path)
            with manager.database.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                now = time.time()
                for name, config, path in zip(names, configs, owned):
                    atomic_json(path / "config.json", config)
                    db.execute(
                        "INSERT INTO experiments(id,config,status,created,updated,game_version) VALUES(?,?,?,?,?,?)",
                        (
                            name,
                            json.dumps(config),
                            "CREATED",
                            now,
                            now,
                            game_version(config["game"]),
                        ),
                    )
                    manager.database.event(db, name, "created", {"batch": request.prefix})
        except Exception:
            for path in owned:
                shutil.rmtree(path)
            raise
        return [manager.inspect(name) for name in names]

    @router.get("/api/v1/research/jobs")
    def list_jobs():
        return jobs.list()

    @router.post("/api/v1/research/jobs", status_code=202)
    def submit_job(request: JobRequest):
        if request.kind in {"behavior", "benchmark", "backup"} and len(request.experiments) != 1:
            raise ValueError("This job requires exactly one experiment")
        if request.kind == "tournament" and len(request.experiments) < 2:
            raise ValueError("A tournament requires at least two experiments")
        return jobs.submit(**request.model_dump())

    @router.get("/api/v1/research/jobs/{identifier}")
    def get_job(identifier: str):
        return jobs.get(identifier)

    @router.get("/api/v1/research/jobs/{identifier}/export")
    def export_job(identifier: str):
        return JSONResponse(
            jobs.get(identifier),
            headers={"Content-Disposition": f'attachment; filename="research-{identifier}.json"'},
        )

    @router.post("/api/v1/research/jobs/{identifier}/cancel")
    def cancel_job(identifier: str):
        return jobs.cancel(identifier)

    @router.delete("/api/v1/research/jobs/{identifier}")
    def delete_job(identifier: str):
        jobs.delete(identifier)
        return {"removed": True}

    @router.get("/api/v1/research/catalog")
    def catalog():
        result = []
        for run in manager.list():
            path = manager.path(run["id"])
            metadata = ResearchStore(path).metadata() if (path / "research.sqlite").exists() else {}
            result.append(
                {
                    "id": run["id"],
                    "tags": metadata.get("tags", []),
                    "notes_preview": metadata.get("notes", "")[:160],
                }
            )
        return result

    @router.get("/api/v1/research/storage")
    def storage():
        runs = []
        for run in manager.list():
            root = manager.path(run["id"])
            files = [
                p
                for p in root.rglob("*")
                if p.is_file() and not p.is_symlink() and root in p.resolve().parents
            ]
            runs.append(
                {
                    "id": run["id"],
                    "status": run["status"],
                    "archived": run["archived"],
                    "bytes": sum(p.stat().st_size for p in files),
                    "research_bytes": (root / "research.sqlite").stat().st_size
                    if (root / "research.sqlite").exists()
                    else 0,
                    "replay_bytes": sum(
                        p.stat().st_size for p in files if p.parent.name == "replays"
                    ),
                }
            )
        disk = shutil.disk_usage(manager.root)
        return {
            "runs": runs,
            "disk_total": disk.total,
            "disk_free": disk.free,
            "backup_bytes": sum(
                p.stat().st_size
                for p in backup_dir(manager.root).glob("*.zip")
                if not p.is_symlink()
            ),
            "research_jobs": len(jobs.list()),
        }

    @router.put("/api/v1/experiments/{experiment}/research/retention")
    def retain(experiment: str, request: Retention):
        with manager._edit_lock(experiment):
            result = store(experiment).retain(request.weight_mib * 1024 * 1024)
            if request.remove_replays:
                directory = manager.path(experiment) / "replays"
                if directory.is_symlink():
                    raise ValueError("Replay directory cannot be a symlink")
                for file in directory.glob("*.json"):
                    file.unlink()
        return result

    @router.get("/api/v1/research/backups")
    def backups():
        import zipfile

        result = []
        for file in sorted(
            backup_dir(manager.root).glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True
        )[:100]:
            if file.is_symlink():
                continue
            try:
                with zipfile.ZipFile(file) as archive:
                    if archive.getinfo("manifest.json").file_size > 256 * 1024:
                        raise ValueError("Manifest too large")
                    manifest = json.loads(archive.read("manifest.json"))
                result.append(
                    {
                        "id": file.stem,
                        "bytes": file.stat().st_size,
                        "experiment": manifest["experiment"],
                        "created": manifest["created"],
                    }
                )
            except (ValueError, KeyError, zipfile.BadZipFile):
                result.append(
                    {
                        "id": file.stem,
                        "bytes": file.stat().st_size,
                        "error": "Invalid backup manifest",
                    }
                )
        return result

    @router.get("/api/v1/research/backups/{identifier}/download")
    def download_backup(identifier: str):
        return FileResponse(
            backup_path(manager.root, identifier),
            filename=f"evoforge-{identifier}.zip",
            media_type="application/zip",
        )

    @router.post("/api/v1/research/backups/{identifier}/verify")
    def verify_backup(identifier: str):
        manifest = validate_archive(backup_path(manager.root, identifier))
        return {
            "verified": True,
            "files": len(manifest["files"]),
            "experiment": manifest["experiment"],
        }

    @router.post("/api/v1/research/backups/{identifier}/restore", status_code=201)
    def restore(identifier: str, request: NamedAction):
        return restore_backup(manager, identifier, request.destination)

    @router.delete("/api/v1/research/backups/{identifier}")
    def remove_backup(identifier: str):
        backup_path(manager.root, identifier).unlink()
        return {"removed": True}

    @router.post("/api/v1/research/backups/import", status_code=201)
    async def upload_backup(request: Request):
        directory = backup_dir(manager.root)
        fd, name = tempfile.mkstemp(dir=directory, prefix=".upload-")
        try:
            count = 0
            with os.fdopen(fd, "wb") as stream:
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > MAX_BYTES:
                        raise HTTPException(413, "Backup exceeds 512 MiB")
                    await run_in_threadpool(stream.write, chunk)
            manifest = await run_in_threadpool(validate_archive, Path(name))
            identifier = uuid.uuid4().hex
            os.replace(name, directory / f"{identifier}.zip")
            return {"id": identifier, "bytes": count, "experiment": manifest["experiment"]}
        finally:
            Path(name).unlink(missing_ok=True)
