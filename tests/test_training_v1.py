from dataclasses import asdict

import pytest
import torch

from evoforge.agents import policy_for
from evoforge.algorithms import evaluate, ppo_refine
from evoforge.core.checkpoints import CheckpointError, migrate, safe_load
from evoforge.service import read_metrics
from evoforge.trainer import Config, Trainer


def config(**kwargs):
    return Config(
        game="coin",
        population=2,
        elites=1,
        ppo_candidates=1,
        ppo_episodes=1,
        eval_episodes=1,
        max_steps=5,
        hidden=[6, 4],
        game_config={"horizon": 4},
        **kwargs,
    )


@pytest.mark.parametrize("mode", ["evolution", "ppo", "hybrid"])
def test_external_training_and_optimizer_resume(tmp_path, mode):
    cfg = config(mode=mode, generations=1)
    first = Trainer(cfg, tmp_path)
    first.run()
    data = safe_load(tmp_path / "checkpoint.pt")
    assert data["schema_version"] == 1
    assert data["architecture"]["input_size"] == 4
    assert data["environment_steps"] >= 56
    assert (
        data["history"][0]["ppo_steps"] > 0
        if mode != "evolution"
        else data["history"][0]["ppo_steps"] == 0
    )
    if mode == "ppo":
        assert all(data["optimizer_states"])
    cfg.generations = 2
    resumed = Trainer(cfg, tmp_path, resume=True)
    resumed.run()
    assert [r["generation"] for r in read_metrics(tmp_path)] == [0, 1]


def test_seeded_evaluation_and_ppo_reproducible():
    model = policy_for("coin", hidden=8)
    assert evaluate(model, [1, 2], game="coin") == evaluate(model, [1, 2], game="coin")
    a = ppo_refine(model, 8, episodes=1, game="coin", epochs=1)
    b = ppo_refine(model, 8, episodes=1, game="coin", epochs=1)
    assert all(torch.equal(x, y) for x, y in zip(a.parameters(), b.parameters()))


def test_exact_resume_matches_uninterrupted_parameters(tmp_path):
    cfg = config(mode="ppo", generations=2)
    full = Trainer(cfg, tmp_path / "full")
    full.run()
    cfg.generations = 1
    Trainer(cfg, tmp_path / "resumed").run()
    cfg.generations = 2
    resumed = Trainer(cfg, tmp_path / "resumed", resume=True)
    resumed.run()
    assert full.environment_steps == resumed.environment_steps
    assert all(
        torch.equal(a, b)
        for x, y in zip(full.population, resumed.population)
        for a, b in zip(x.parameters(), y.parameters())
    )


def test_recovery_reconciles_metrics_and_rejects_architecture(tmp_path):
    cfg = config(mode="evolution", generations=2)
    Trainer(cfg, tmp_path).run()
    (tmp_path / "checkpoint.pt").write_bytes(b"partial")
    resumed = Trainer(cfg, tmp_path, resume=True)
    assert resumed.generation == 1 and resumed.checkpoint_recovered
    assert [r["generation"] for r in read_metrics(tmp_path)] == [0]
    resumed.run()
    assert [r["generation"] for r in read_metrics(tmp_path)] == [0, 1]
    cfg.hidden = 10
    with pytest.raises(ValueError, match="config differs"):
        Trainer(cfg, tmp_path, resume=True)


def test_safe_legacy_migration_and_checksum(tmp_path):
    path = tmp_path / "legacy.pt"
    torch.save({"config": asdict(Config()), "state_dict": policy_for().state_dict()}, path)
    raw = path.read_bytes()
    assert migrate(path)["from_schema"] == 0
    assert path.read_bytes() == raw
    migrate(path, dry_run=False)
    assert path.with_name("legacy.pt.v090-original").read_bytes() == raw
    assert safe_load(path)["schema_version"] == 1
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(raw)
    with pytest.raises(CheckpointError, match="checksum"):
        safe_load(path)


def test_untrusted_pickle_cannot_execute(tmp_path):
    class Exploit:
        def __reduce__(self):
            return (eval, ("__import__('pathlib').Path(%r).touch()" % str(tmp_path / "executed"),))

    torch.save({"object": Exploit()}, tmp_path / "bad.pt")
    with pytest.raises(CheckpointError, match="safely"):
        safe_load(tmp_path / "bad.pt")
    assert not (tmp_path / "executed").exists()


def test_invalid_training_config_and_game_selection(tmp_path):
    for changes in ({"max_steps": 0}, {"hidden": []}, {"mutation_sigma": float("nan")}):
        cfg = config(generations=1)
        for k, v in changes.items():
            setattr(cfg, k, v)
        with pytest.raises(ValueError):
            cfg.validate()
    # A four-input Coin policy cannot run even one Snake observation.
    model = policy_for("coin")
    assert ppo_refine(model, 4, episodes=1, game="coin").training_stats["steps"] == 12
