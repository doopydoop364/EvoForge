import json
import subprocess
import sys

import pytest

from evoforge.core.experiments import compare, export_metrics
from evoforge.doctor import diagnose
from evoforge.supervisor import Supervisor
from evoforge.trainer import Config, Trainer


def test_metrics_database_exports_and_budget_comparison(tmp_path):
    manager = Supervisor(tmp_path)
    for name, mode in [("one", "evolution"), ("two", "ppo")]:
        cfg = Config(
            game="coin",
            mode=mode,
            population=2,
            elites=1,
            ppo_candidates=0,
            generations=2,
            eval_episodes=1,
            ppo_episodes=1,
            hidden=8,
        )
        manager.create(name, cfg)
        trainer = Trainer(cfg, manager.path(name))
        trainer.on_commit = lambda current, name=name: manager.database.sync_metrics(
            name, current.history
        )
        trainer.run()
        assert len(json.loads(export_metrics(manager.path(name)))) == 2
        assert "environment_steps" in export_metrics(manager.path(name), "csv")
    with manager.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 4
    result = compare(manager, ["one", "two"])
    assert all(
        r["actual_environment_steps"] <= result["environment_step_budget"]
        for r in result["results"]
    )
    assert result["results"][0]["withheld_test"] is None
    with pytest.raises(ValueError, match="no committed"):
        compare(manager, ["one", "two"], 1)


def test_cli_headless_version_discovery_doctor_and_train(tmp_path):
    def cli(*args):
        result = subprocess.run(
            [sys.executable, "-m", "evoforge.cli", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    assert "Headless session" in cli()
    assert cli("version").strip() == "1.0.0rc1"
    assert "coin" in cli("games", "list")
    assert json.loads(cli("games", "validate", "coin"))["valid"]
    cfg = tmp_path / "cfg.json"
    cfg.write_text(
        json.dumps(
            {
                "game": "coin",
                "mode": "evolution",
                "population": 2,
                "elites": 1,
                "ppo_candidates": 0,
                "generations": 1,
                "eval_episodes": 1,
                "hidden": [8, 4],
            }
        )
    )
    cli("train", "--config-file", str(cfg), "--output", str(tmp_path / "runs" / "cli-run"))
    rows = json.loads(cli("experiments", "export", "cli-run", "--root", str(tmp_path / "runs")))
    assert len(rows) == 1
    assert (
        json.loads(cli("workers", "status", "cli-run", "--root", str(tmp_path / "runs")))["status"]
        == "COMPLETED"
    )
    report = diagnose(tmp_path / "doctor")
    assert report["execution_default"] == "cpu" and report["storage_writable"]
    assert "kernel_test" in report["gpu"]


pytestmark = pytest.mark.integration
