import json
import os

from evoforge.service import RunService, read_metrics, summarize
from evoforge.trainer import Config, Trainer


def test_run_service_snapshot_reads_legacy_and_current_run_files(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"game": "snake"}))
    (tmp_path / "worker.json").write_text(json.dumps({"state": "running", "pid": os.getpid(), "generation": 3}))
    (tmp_path / "metrics.csv").write_text("generation,best_train,mean_train\n0,1.5,1\n1,3,2\n")
    (tmp_path / "checkpoint.pt").touch()
    snap = RunService(tmp_path).snapshot()
    assert snap["worker"]["state"] == "running"
    assert snap["checkpoint"] is True
    assert snap["metrics"]["trend"] == 1.5
    assert snap["metrics"]["best"] == 3


def test_summary_handles_empty_and_single_generation():
    assert summarize([]) == {"generations": 0, "latest": None, "best": None, "trend": None}
    assert summarize([{"best_train": 2}])["trend"] is None


def test_metrics_remain_readable_without_new_columns(tmp_path):
    (tmp_path / "metrics.csv").write_text("generation,best_train\n0,4\n")
    assert read_metrics(tmp_path)[0] == {"generation": 0, "best_train": 4}


def test_metric_append_expands_legacy_csv_header_without_shifting_rows(tmp_path):
    (tmp_path / "metrics.csv").write_text("generation,best_train\n0,4\n")
    trainer = Trainer(Config(population=2, elites=1, ppo_candidates=0), tmp_path)
    trainer._append_metric({"generation": 1, "best_train": 5, "median_train": 4.5})
    rows = read_metrics(tmp_path)
    assert rows[0]["best_train"] == 4
    assert rows[0]["median_train"] == ""
    assert rows[1]["best_train"] == 5
    assert rows[1]["median_train"] == 4.5


def test_trainer_recovers_previous_checkpoint_when_latest_is_corrupt(tmp_path):
    config = Config(population=2, elites=1, generations=2, eval_episodes=1, ppo_episodes=1, ppo_candidates=0)
    trainer = Trainer(config, tmp_path)
    trainer._save()
    trainer.generation = 1
    trainer._save()
    trainer.checkpoint.write_bytes(b"partial checkpoint")
    recovered = Trainer(Config(population=2, elites=1, generations=2, eval_episodes=1, ppo_episodes=1, ppo_candidates=0), tmp_path, resume=True)
    assert recovered.generation == 0
    assert recovered.checkpoint_recovered is True
