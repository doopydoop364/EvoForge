"""Integrity checked, atomic tensor archives with restricted legacy readers."""

import hashlib
import io
import os
import shutil
import tempfile
from pathlib import Path

import torch

MAGIC = b"EVOFORGE-1\n"
SCHEMA_VERSION = 1


class CheckpointError(ValueError):
    pass


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path, data):
    import json

    atomic_bytes(path, json.dumps(data, indent=2, allow_nan=False).encode())


def safe_load(path):
    """Never falls back to unrestricted pickle. v0.9 tensor/primitive dicts work."""
    try:
        raw = Path(path).read_bytes()
        if raw.startswith(MAGIC):
            digest, payload = raw[len(MAGIC) :].split(b"\n", 1)
            if hashlib.sha256(payload).hexdigest().encode() != digest:
                raise CheckpointError("Checkpoint integrity checksum mismatch")
        else:
            payload = raw
        data = torch.load(io.BytesIO(payload), map_location="cpu", weights_only=True)
        if not isinstance(data, dict):
            raise CheckpointError("Checkpoint must contain a mapping")
        version = data.get("schema_version", 0)
        if version not in (0, SCHEMA_VERSION):
            raise CheckpointError(f"Unsupported checkpoint schema {version}")
        return data
    except (OSError, CheckpointError):
        raise
    except Exception as exc:
        raise CheckpointError(
            f"Cannot safely read {Path(path).name}: {exc}. No unsafe pickle fallback is permitted."
        ) from exc


def save(path, payload, backup=True):
    path = Path(path)
    stream = io.BytesIO()
    torch.save({**payload, "schema_version": SCHEMA_VERSION}, stream)
    raw = stream.getvalue()
    if backup and path.exists():
        # Never replace a good backup with an already corrupt primary.
        try:
            safe_load(path)
        except (OSError, CheckpointError):
            pass
        else:
            atomic_bytes(path.with_name(path.name + ".bak"), path.read_bytes())
    atomic_bytes(path, MAGIC + hashlib.sha256(raw).hexdigest().encode() + b"\n" + raw)


def load_recovering(path):
    path = Path(path)
    try:
        return safe_load(path), False
    except (OSError, CheckpointError) as primary:
        try:
            return safe_load(path.with_name(path.name + ".bak")), True
        except (OSError, CheckpointError) as backup:
            raise CheckpointError(
                f"Primary and backup unusable: {primary}; backup: {backup}"
            ) from primary


def migrate(path, dry_run=True):
    """Explicit conversion; preserve an immutable original alongside the file."""
    path = Path(path)
    data = safe_load(path)
    result = {
        "path": str(path),
        "from_schema": data.get("schema_version", 0),
        "to_schema": SCHEMA_VERSION,
        "dry_run": dry_run,
    }
    if not dry_run and data.get("schema_version", 0) == 0:
        backup = path.with_name(path.name + ".v090-original")
        if backup.exists():
            raise CheckpointError(f"Migration backup already exists: {backup}")
        shutil.copy2(path, backup)
        save(path, data)
    return result
