import csv
import json

from evoforge.dashboard import _lines, _metric, launch


def test_dashboard_helpers(tmp_path):
    assert _lines(tmp_path / "missing") == []
    assert _metric(tmp_path / "missing") is None
    (tmp_path / "training.log").write_text("hello\nworld\n")
    assert _lines(tmp_path / "training.log", 1) == ["world"]
    with (tmp_path / "metrics.csv").open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["generation", "best_train"])
        wr.writeheader()
        wr.writerow({"generation": 0, "best_train": 1.25})
    assert _metric(tmp_path / "metrics.csv")["best_train"] == "1.25"
    cmd = launch(tmp_path)
    assert cmd[-2:] == ["--output", str(tmp_path)]


def test_resume_uses_original_settings(tmp_path):
    cfg = dict(
        mode="evolution",
        population=6,
        generations=10,
        elites=2,
        ppo_candidates=0,
        ppo_episodes=2,
        eval_episodes=2,
        size=9,
        max_steps=100,
        seed=42,
        hidden=64,
    )
    (tmp_path / "checkpoint.pt").write_bytes(b"placeholder")
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    cmd = launch(tmp_path)
    assert "--resume" in cmd
    assert cmd[cmd.index("--population") + 1] == "6"
