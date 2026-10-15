"""Portable, checksummed experiment backups. Restores always create a new run."""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

import torch

from evoforge.core.checkpoints import atomic_json, safe_load
from evoforge.policy import Policy

MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 512
FIXED = {
    "config.json",
    "checkpoint.pt",
    "checkpoint.pt.bak",
    "champion.pt",
    "spectator.pt",
    "metrics.csv",
    "research.sqlite",
}


def allowed(name):
    return name in FIXED or bool(re.fullmatch(r"replays/[a-f0-9]{32}\.json", name))


def backup_dir(root):
    path = Path(root) / ".research-backups"
    path.mkdir(exist_ok=True)
    if path.is_symlink():
        raise ValueError("Backup directory cannot be a symlink")
    return path


def backup_path(root, identifier):
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Invalid backup identifier")
    path = backup_dir(root) / f"{identifier}.zip"
    if path.is_symlink() or not path.is_file():
        raise KeyError(identifier)
    return path


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(manager, experiment, check=lambda: None):
    identifier = uuid.uuid4().hex
    directory = backup_dir(manager.root)
    target = directory / f"{identifier}.zip"
    with manager._edit_lock(experiment), tempfile.TemporaryDirectory(dir=directory) as temp:
        staging = Path(temp)
        source = manager.path(experiment)
        total, files = 0, {}
        candidates = [source / name for name in sorted(FIXED)]
        candidates.extend(sorted((source / "replays").glob("*.json")))
        for file in candidates:
            check()
            if not file.is_file():
                continue
            relative = file.relative_to(source).as_posix()
            if file.is_symlink() or file.parent.is_symlink() or not allowed(relative):
                raise ValueError("Backup contains an unsupported path")
            total += file.stat().st_size
            if total > MAX_BYTES or len(files) >= MAX_FILES - 1:
                raise ValueError("Backup exceeds 512 MiB or 511 data files")
            destination = staging / relative
            destination.parent.mkdir(exist_ok=True)
            if file.suffix == ".sqlite":
                with sqlite3.connect(f"file:{file}?mode=ro", uri=True) as src:
                    with sqlite3.connect(destination) as dst:
                        src.backup(dst)
            else:
                shutil.copyfile(file, destination)
            files[relative] = {
                "bytes": destination.stat().st_size,
                "sha256": digest_file(destination),
            }
        manifest = {
            "format": 1,
            "experiment": experiment,
            "created": time.time(),
            "files": files,
            "scope": "config, checkpoints, research annotations/history and captured replays; no worker processes",
        }
        atomic_json(staging / "manifest.json", manifest)
        temporary = staging / "archive.zip"
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1
        ) as archive:
            archive.write(staging / "manifest.json", "manifest.json")
            for relative in files:
                check()
                archive.write(staging / relative, relative)
        validate_archive(temporary)
        os.replace(temporary, target)
    return {"id": identifier, "bytes": target.stat().st_size, **manifest}


def validate_archive(path, destination=None):
    """Bound decompression, verify every member, then verify scientific artifacts."""
    if Path(path).stat().st_size > MAX_BYTES:
        raise ValueError("Backup exceeds 512 MiB")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [i.filename for i in entries]
            if (
                len(entries) > MAX_FILES
                or len(set(names)) != len(names)
                or "manifest.json" not in names
            ):
                raise ValueError("Invalid backup structure")
            if sum(i.file_size for i in entries) > MAX_BYTES:
                raise ValueError("Expanded backup exceeds 512 MiB")
            for item in entries:
                if item.filename != "manifest.json" and not allowed(item.filename):
                    raise ValueError("Unsupported backup member")
                if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise ValueError("Links/encrypted members are unsupported")
            info = archive.getinfo("manifest.json")
            if info.file_size > 256 * 1024:
                raise ValueError("Manifest too large")
            manifest = json.loads(archive.read(info))
            if manifest.get("format") != 1 or not isinstance(manifest.get("files"), dict):
                raise ValueError("Unsupported backup manifest")
            if (
                set(manifest["files"]) != set(names) - {"manifest.json"}
                or "config.json" not in names
            ):
                raise ValueError("Manifest members do not match archive")
            with tempfile.TemporaryDirectory() as temp:
                staging = Path(temp) if destination is None else Path(destination)
                for name, metadata in manifest["files"].items():
                    item = archive.getinfo(name)
                    if item.file_size != metadata["bytes"]:
                        raise ValueError("Backup member size mismatch")
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    digest, count = hashlib.sha256(), 0
                    with archive.open(item) as src, target.open("xb") as dst:
                        while chunk := src.read(1024 * 1024):
                            count += len(chunk)
                            if count > item.file_size:
                                raise ValueError("Backup decompression limit exceeded")
                            digest.update(chunk)
                            dst.write(chunk)
                    if count != item.file_size or digest.hexdigest() != metadata["sha256"]:
                        raise ValueError("Backup checksum mismatch")
                validate_artifacts(staging)
            return manifest
    except (zipfile.BadZipFile, KeyError, TypeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid backup: {exc}") from exc


def validate_artifacts(directory):
    from evoforge.api.schemas import TrainingConfig
    from evoforge.telemetry.recordings import Recording

    config = TrainingConfig.model_validate_json(
        (directory / "config.json").read_text()
    ).model_dump()
    for name in ("checkpoint.pt", "checkpoint.pt.bak", "champion.pt", "spectator.pt"):
        path = directory / name
        if not path.exists():
            continue
        data = safe_load(path, max_bytes=MAX_BYTES)
        if data.get("config") != config:
            # Existing checkpoints may omit defaults and may precede a generation extension.
            recorded = TrainingConfig.model_validate(data.get("config", {})).model_dump()
            recorded.pop("generations")
            actual = {k: v for k, v in config.items() if k != "generations"}
            if recorded != actual:
                raise ValueError(f"{name}: checkpoint configuration mismatch")
        architecture = data.get("architecture")
        if not isinstance(architecture, dict):
            raise ValueError(f"{name}: architecture is required")
        dims = [
            architecture.get("input_size", 0),
            architecture.get("actions", 0),
            *architecture.get("hidden", []),
        ]
        if (
            not dims
            or any(type(n) is not int or n < 1 or n > 65536 for n in dims)
            or len(dims) > 10
        ):
            raise ValueError("Invalid policy dimensions")
        if sum(a * b for a, b in zip(dims[:1] + dims[2:], dims[2:] + dims[1:2])) > 8_000_000:
            raise ValueError("Policy exceeds backup validation resource limit")
        with torch.random.fork_rng():
            model = Policy(**architecture)
        states = data.get("population", data.get("policies", [data.get("state_dict")]))
        if not isinstance(states, list) or not states or len(states) > 4096:
            raise ValueError("Invalid checkpoint population")
        if name.startswith("checkpoint") and len(states) != config["population"]:
            raise ValueError("Checkpoint population does not match config")
        if name.startswith("checkpoint"):
            import random

            import numpy as np

            try:
                generation = data["generation"]
                if type(generation) is not int or not 0 <= generation <= 1000000:
                    raise ValueError("Invalid checkpoint generation")
                np.random.default_rng().bit_generator.state = data["numpy_state"]
                torch.Generator(device="cpu").set_state(data["torch_state"])
                random.Random().setstate(data["python_state"])
                history = data.get("history", [])
                if not isinstance(history, list) or len(history) > generation:
                    raise ValueError("Invalid checkpoint history")
                indices = [r["generation"] for r in history]
                if indices != sorted(set(indices)) or any(
                    type(g) is not int or not 0 <= g < generation for g in indices
                ):
                    raise ValueError("History generations do not match checkpoint")
                json.dumps(history, allow_nan=False)
                optimizers = data.get("optimizer_states", [None] * len(states))
                if len(optimizers) != len(states):
                    raise ValueError("Optimizer states do not match population")
            except (KeyError, RuntimeError, TypeError) as exc:
                raise ValueError(f"Invalid checkpoint continuation state: {exc}") from exc
        for state in states + ([data["champion"]] if data.get("champion") else []):
            try:
                if not all(torch.isfinite(value).all() for value in state.values()):
                    raise ValueError("Non-finite model parameters")
                model.load_state_dict(state, strict=True)
            except (RuntimeError, AttributeError, TypeError) as exc:
                raise ValueError(f"Invalid checkpoint parameters: {exc}") from exc
    research = directory / "research.sqlite"
    if research.exists():
        with sqlite3.connect(f"file:{research}?mode=ro&immutable=1", uri=True) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Research database integrity check failed")
            expected = {"metadata", "nodes", "history", "bookmarks"}
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if (
                tables != expected
                or db.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('trigger','view')"
                ).fetchone()[0]
            ):
                raise ValueError("Unsupported research database schema")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (1, 2):
                raise ValueError("Unsupported research database version")
            columns = {
                "metadata": {"key", "value"},
                "nodes": {
                    "id",
                    "generation",
                    "slot",
                    "operation",
                    "parents",
                    "fingerprint",
                    "descriptor",
                    "weights",
                    "fitness",
                },
                "history": {"generation", "data"},
                "bookmarks": {"id", "title", "view", "generation", "agent", "notes", "created"},
            }
            if version == 2:
                columns["bookmarks"].add("right_agent")
            for table, expected_columns in columns.items():
                actual_columns = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                if actual_columns != expected_columns:
                    raise ValueError("Unsupported research table columns")
            for descriptor, raw, fingerprint in db.execute(
                "SELECT descriptor,weights,fingerprint FROM nodes WHERE weights IS NOT NULL"
            ):
                if hashlib.sha256(descriptor.encode() + b"\0" + raw).hexdigest() != fingerprint:
                    raise ValueError("Research parameter fingerprint mismatch")
                import numpy as np

                if len(raw) % 4 or not np.isfinite(np.frombuffer(raw, dtype="<f4")).all():
                    raise ValueError("Invalid research parameters")
                structure = json.loads(descriptor)
                parts = structure.get("layout", [])
                offset = 0
                names = set()
                if not parts or len(parts) > 32:
                    raise ValueError("Invalid research parameter layout")
                for part in parts:
                    if (
                        part["name"] in names
                        or part["offset"] != offset
                        or not part["shape"]
                        or len(part["shape"]) > 2
                        or any(type(n) is not int or not 1 <= n <= 65536 for n in part["shape"])
                        or int(np.prod(part["shape"])) != part["count"]
                    ):
                        raise ValueError("Invalid research parameter layout")
                    names.add(part["name"])
                    offset += part["count"]
                if offset * 4 != len(raw):
                    raise ValueError("Research parameter length mismatch")
    for replay in (directory / "replays").glob("*.json"):
        if replay.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Replay exceeds 8 MiB")
        Recording.model_validate_json(replay.read_bytes())


def restore_backup(manager, identifier, destination):
    target = manager.path(destination)
    if target.exists():
        raise ValueError("Restore requires a new experiment name")
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=manager.root) as temp:
        staging = Path(temp) / "run"
        staging.mkdir()
        manifest = validate_archive(backup_path(manager.root, identifier), staging)
        # Validate the installed environment before publishing any new experiment.
        from evoforge.trainer import Config

        Config(**json.loads((staging / "config.json").read_text())).validate()
        # Reserve target atomically. Never replace an existing run, even in a race.
        target.mkdir()
        try:
            for source in staging.iterdir():
                shutil.move(str(source), target / source.name)
            atomic_json(
                target / "restore-provenance.json",
                {"backup": identifier, "source": manifest["experiment"], "restored": time.time()},
            )
            manager.register(destination)
        except Exception:
            shutil.rmtree(target)
            raise
    return manager.inspect(destination)
