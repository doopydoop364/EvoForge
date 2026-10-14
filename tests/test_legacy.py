"""Generate real v0.9 runs from the pinned baseline, then migrate/resume them."""

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from evoforge.agents.serialization import load_policy
from evoforge.core.checkpoints import migrate
from evoforge.service import read_metrics
from evoforge.trainer import Config, Trainer


@pytest.mark.parametrize("game", ["snake", "flappy"])
def test_actual_v090_checkpoint_resume_and_preservation(tmp_path, game):
    repo = Path(__file__).resolve().parents[1]
    archive = subprocess.run(
        ["git", "archive", "938b597", "evoforge"], cwd=repo, capture_output=True, check=True
    ).stdout
    source = tmp_path / "baseline"
    source.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        # Only trusted, repository-authored Python files from this pinned commit.
        for member in tar.getmembers():
            if (
                member.isfile()
                and member.name.startswith("evoforge/")
                and member.name.endswith(".py")
            ):
                path = source / member.name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(tar.extractfile(member).read())
    run = tmp_path / "run"
    script = """from evoforge.trainer import Trainer, Config
import sys
Trainer(Config(game=sys.argv[1],mode="evolution",population=2,elites=1,ppo_candidates=0,
               generations=1,eval_episodes=1,max_steps=8,hidden=8),sys.argv[2]).run()
"""
    subprocess.run(
        [sys.executable, "-c", script, game, str(run)],
        cwd=source,
        check=True,
        capture_output=True,
        timeout=20,
    )
    original = (run / "checkpoint.pt").read_bytes()
    policy, cfg = load_policy(run / "champion.pt")
    assert cfg["game"] == game and policy.architecture["input_size"] == 17
    assert migrate(run / "checkpoint.pt")["from_schema"] == 0
    assert (run / "checkpoint.pt").read_bytes() == original
    config = Config(**json.loads((run / "config.json").read_text()))
    config.generations = 2
    trainer = Trainer(config, run, resume=True)
    assert trainer.generation == 1
    trainer.run()
    assert (run / "checkpoint.pt.bak").read_bytes() == original
    assert [r["generation"] for r in read_metrics(run)] == [0, 1]


pytestmark = pytest.mark.integration
