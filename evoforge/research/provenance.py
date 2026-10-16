"""A recorded environment identity, independent of an external asset's filename."""

import hashlib
import os
import platform
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch

from evoforge import __version__
from evoforge.games import game_version


def environment_identity(config):
    identity = {
        "game": config.game,
        "plugin_version": game_version(config.game),
        "size": config.size,
        "max_steps": config.max_steps,
        "game_config": config.game_config,
    }
    if config.game == "geometrydash":
        path = os.environ.get("EVOFORGE_GMD_LEVEL")
        identity["external_level_sha256"] = (
            hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else None
        )
        identity["importer_sha256"] = hashlib.sha256(
            (Path(__file__).parents[1] / "gmd_import.py").read_bytes()
        ).hexdigest()
    return identity


def manifest(config):
    source = hashlib.sha256()
    package = Path(__file__).parents[1]
    for path in sorted(package.rglob("*.py")):
        source.update(str(path.relative_to(package)).encode())
        source.update(path.read_bytes())
    return {
        "format": 1,
        "engine": __version__,
        "source_sha256": source.hexdigest(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "torch": str(torch.__version__),
        "platform": platform.platform(),
        "config": asdict(config),
        "environment": environment_identity(config),
        "rng": ["numpy.PCG64", "torch.cpu", "python.random"],
        "checkpoint_population": "next population; history scores describe the evaluated generation",
        "evaluation": {
            "validation_seeds": [config.seed + 900000 + i for i in range(12)],
            "validation_reused_for_selection": True,
            "withheld_test": None,
        },
    }
