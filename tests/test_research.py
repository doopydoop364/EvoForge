"""Research workspace acceptance: lineage, data integrity, jobs and authenticated APIs."""

import hashlib
import json
import time
import zipfile
from dataclasses import asdict

import numpy as np
import pytest
from fastapi.testclient import TestClient

from evoforge.api.app import create_app
from evoforge.core.checkpoints import atomic_json, safe_load, save
from evoforge.research.analysis import genetic_comparison
from evoforge.research.archive import create_backup, restore_backup, validate_archive
from evoforge.research.jobs import Jobs
from evoforge.research.rps import RPS
from evoforge.research.store import ResearchStore
from evoforge.supervisor import Supervisor, WorkerConflict
from evoforge.trainer import Config, Trainer


def small(**overrides):
    return Config(
        **{
            "game": "rps",
            "mode": "evolution",
            "population": 3,
            "elites": 1,
            "ppo_candidates": 0,
            "ppo_episodes": 1,
            "eval_episodes": 1,
            "generations": 2,
            "max_steps": 3,
            "hidden": 4,
            **overrides,
        }
    )


def trained(tmp_path, name="alpha", **overrides):
    manager = Supervisor(tmp_path)
    cfg = small(**overrides)
    manager.create(name, cfg)
    Trainer(cfg, manager.path(name)).run()
    return manager


def test_lineage_identity_scores_asof_and_recovery(tmp_path):
    trained(tmp_path)
    store = ResearchStore(tmp_path / "alpha")
    family = store.family(2)
    assert len(family["nodes"]) == 9
    assert all(n["fingerprint"] for n in family["nodes"])
    assert family["nodes"][-1]["parents"]
    assert all(n["fitness"] is None for n in family["nodes"] if n["generation"] == 2)
    assert all(n["fitness"] is None for n in store.family(0)["nodes"])
    assert store.generation(0)["population_fitness"]
    store.annotate("A hypothesis", ["baseline"])
    mark = store.bookmark("Interesting parent", "Family Trees", 1, "1:0")
    backup = safe_load(tmp_path / "alpha/checkpoint.pt.bak")
    store.sync(backup)
    assert store.metadata()["indexed_generation"] == 1
    assert store.generation(1) is None
    assert not any(n["generation"] > 1 for n in store.family(2)["nodes"])
    assert store.metadata()["notes"] == "A hypothesis"
    assert store.bookmarks()[0]["id"] == mark["id"]


def test_ppo_ancestry_and_genetic_behavior_identity(tmp_path):
    trained(tmp_path, mode="ppo", generations=1)
    store = ResearchStore(tmp_path / "alpha")
    nodes = store.family(1)["nodes"]
    assert [n["parents"] for n in nodes if n["generation"] == 1] == [["0:0"], ["0:1"], ["0:2"]]
    result = genetic_comparison(store, "1:0", "1:0")
    assert all(layer["changed"] == 0 and layer["rmse"] == 0 for layer in result["layers"])
    assert all(len(layer["samples"]) <= 96 for layer in result["layers"])


def test_retention_preserves_notes_lineage_and_checkpoint(tmp_path):
    trained(tmp_path)
    checkpoint = (tmp_path / "alpha/checkpoint.pt").read_bytes()
    store = ResearchStore(tmp_path / "alpha")
    store.annotate("keep me", ["test"])
    result = store.retain(0)
    assert result["retained_weight_bytes"] == 0
    assert store.metadata()["notes"] == "keep me"
    assert store.family(2)["total"] == 9
    assert store.generation(0)
    assert (tmp_path / "alpha/checkpoint.pt").read_bytes() == checkpoint
    with pytest.raises(ValueError, match="not recorded|retention"):
        store.weights("2:0")


def test_history_response_bounded_endpoints_and_exact_detail(tmp_path):
    store = ResearchStore(tmp_path)
    with store.connect() as db:
        db.executemany(
            "INSERT INTO history VALUES (?,?)",
            [(i, json.dumps({"generation": i, "best_train": i})) for i in range(10000)],
        )
    data = store.history(limit=50)
    assert data["sampled"] and data["total"] == 10000
    assert len(data["rows"]) <= 50
    assert data["rows"][0]["generation"] == 0
    assert data["rows"][-1]["generation"] == 9999
    assert store.generation(4729)["best_train"] == 4729


def test_backup_roundtrip_and_rename_preserve_research(tmp_path):
    manager = trained(tmp_path)
    store = ResearchStore(manager.path("alpha"))
    store.annotate("Retain provenance", ["baseline"])
    store.bookmark("Champion ancestry", "Family Trees", 1, "1:0")
    backup = create_backup(manager, "alpha")
    path = tmp_path / ".research-backups" / f"{backup['id']}.zip"
    assert validate_archive(path)["files"]["research.sqlite"]
    restored = restore_backup(manager, backup["id"], "restored")
    assert restored["status"] == "CREATED" and restored["worker"] is None
    assert ResearchStore(manager.path("restored")).metadata()["notes"] == "Retain provenance"
    assert safe_load(manager.path("restored") / "checkpoint.pt")["generation"] == 2
    manager.rename("restored", "renamed")
    assert ResearchStore(manager.path("renamed")).bookmarks()[0]["agent"] == "1:0"
    with pytest.raises(ValueError, match="new experiment"):
        restore_backup(manager, backup["id"], "alpha")


def rewrite_archive(source, destination, mutate):
    with zipfile.ZipFile(source) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    mutate(files)
    with zipfile.ZipFile(destination, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def test_archive_rejects_traversal_checksum_and_nonfinite_models(tmp_path):
    manager = trained(tmp_path)
    backup = create_backup(manager, "alpha")
    source = tmp_path / ".research-backups" / f"{backup['id']}.zip"
    evil = tmp_path / "evil.zip"
    rewrite_archive(source, evil, lambda files: files.update({"../escaped": b"x"}))
    with pytest.raises(ValueError, match="Unsupported backup member"):
        validate_archive(evil)
    assert not (tmp_path / "escaped").exists()
    rewrite_archive(source, evil, lambda files: files.update({"config.json": b"{}"}))
    with pytest.raises(ValueError, match="size mismatch|checksum"):
        validate_archive(evil)
    state = safe_load(manager.path("alpha") / "checkpoint.pt")
    next(iter(state["population"][0].values())).flatten()[0] = float("nan")
    save(tmp_path / "bad.pt", state, backup=False)

    def tamper(files):
        files["checkpoint.pt"] = (tmp_path / "bad.pt").read_bytes()
        manifest = json.loads(files["manifest.json"])
        manifest["files"]["checkpoint.pt"] = {
            "bytes": len(files["checkpoint.pt"]),
            "sha256": hashlib.sha256(files["checkpoint.pt"]).hexdigest(),
        }
        files["manifest.json"] = json.dumps(manifest).encode()

    rewrite_archive(source, evil, tamper)
    with pytest.raises(ValueError, match="Non-finite"):
        validate_archive(evil)


def test_api_auth_notes_batch_bookmarks_and_upload(tmp_path):
    app = create_app(tmp_path, token="secret")
    client = TestClient(app)
    headers = {"Authorization": "Bearer secret"}
    assert client.get("/api/v1/research/storage").status_code == 401
    assert client.post("/api/v1/research/backups/import", content=b"not a zip").status_code == 401
    payload = {"prefix": "replicate", "seeds": [1, 2], "config": asdict(small())}
    assert client.post("/api/v1/research/batches", json=payload, headers=headers).status_code == 201
    assert client.post("/api/v1/research/batches", json=payload, headers=headers).status_code == 422
    base = "/api/v1/experiments/replicate-1/research"
    assert (
        client.put(
            base, json={"notes": "<script>not executable</script>", "tags": ["a"]}, headers=headers
        ).status_code
        == 200
    )
    assert client.get(base, headers=headers).json()["notes"].startswith("<script>")
    assert (
        client.put(base, json={"notes": "x", "tags": ["a" * 41]}, headers=headers).status_code
        == 422
    )
    assert client.put(base, json={"notes": "x" * 70000}, headers=headers).status_code == 413
    assert (
        client.get(
            "/api/v1/research/storage", headers={**headers, "Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/research/backups/import", content=b"not a zip", headers=headers
        ).status_code
        == 422
    )
    assert not list((tmp_path / ".research-backups").glob(".upload-*"))
    backup = create_backup(app.state.supervisor, "replicate-1")
    raw = (tmp_path / ".research-backups" / f"{backup['id']}.zip").read_bytes()
    response = client.post("/api/v1/research/backups/import", content=raw, headers=headers)
    assert response.status_code == 201
    assert response.json()["id"] != backup["id"]


def test_changed_environment_blocks_resume(tmp_path, monkeypatch):
    cfg = small(generations=1)
    Trainer(cfg, tmp_path).run()
    from evoforge.research import provenance

    original = provenance.environment_identity
    monkeypatch.setattr(
        provenance, "environment_identity", lambda config: {**original(config), "changed": True}
    )
    with pytest.raises(ValueError, match="Environment content differs"):
        Trainer(cfg, tmp_path, resume=True)


def test_rps_simultaneous_history_and_repeatability():
    a, b = RPS("cycle", 5), RPS("cycle", 5)
    a.reset(123)
    b.reset(123)
    for action in [0, 2, 1, 1, 0]:
        result, expected = a.step(action), b.step(action)
        assert np.array_equal(result[0], expected[0]) and result[1:] == expected[1:]
    assert result[2]
    with pytest.raises(ValueError):
        a.step(0)
    a = RPS("repeat", 3)
    a.reset(5)
    a.step(2)
    # Repeat selects the previous action, even when the current move is different.
    obs, reward, *_ = a.step(0)
    assert obs[2] == 1 and reward == 1


@pytest.mark.integration
def test_detached_jobs_persist_and_same_agent_behavior(tmp_path):
    manager = trained(tmp_path, generations=1)
    jobs = Jobs(manager)
    job = jobs.submit("behavior", ["alpha"], episodes=1, agents=["1:0", "1:0"])
    # A new service instance sees the same job and cannot submit concurrently.
    other = Jobs(Supervisor(tmp_path))
    with pytest.raises(WorkerConflict):
        other.submit("benchmark", ["alpha"], episodes=1)
    deadline = time.monotonic() + 30
    while True:
        result = other.get(job["id"])
        if result["status"] not in {"queued", "running"}:
            break
        assert time.monotonic() < deadline
        time.sleep(0.05)
    assert result["status"] == "completed", result
    assert result["result"]["action_agreement"] == 1
    assert result["result"]["mean_js_divergence_nats"] == 0
    assert (jobs.path(job["id"]) / "input-0.pt").is_file()
    other.delete(job["id"])
    with pytest.raises(KeyError):
        other.get(job["id"])


@pytest.mark.integration
def test_cancelled_job_and_reproducible_tournament(tmp_path):
    manager = trained(tmp_path, generations=1)
    trained(tmp_path, name="beta", generations=1, seed=9)
    jobs = Jobs(manager)
    cancelled = jobs.submit("benchmark", ["alpha"], episodes=1)
    jobs.cancel(cancelled["id"])
    deadline = time.monotonic() + 30
    while jobs.get(cancelled["id"])["status"] in {"queued", "running"}:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    assert jobs.get(cancelled["id"])["status"] == "cancelled"
    outputs = []
    for _ in range(2):
        job = jobs.submit("tournament", ["alpha", "beta"], seed=80, episodes=3)
        deadline = time.monotonic() + 30
        while jobs.get(job["id"])["status"] in {"queued", "running"}:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        result = jobs.get(job["id"])
        assert result["status"] == "completed", result
        outputs.append(result["result"])
    assert outputs[0]["results"] == outputs[1]["results"]
    assert outputs[0]["seeds"] == [80, 81, 82]
    assert outputs[0]["pairs"] == outputs[1]["pairs"]


def test_stale_job_is_interrupted_not_completed(tmp_path):
    jobs = Jobs(Supervisor(tmp_path))
    identifier = "a" * 32
    path = jobs.root / identifier
    path.mkdir()
    atomic_json(
        path / "job.json",
        {"id": identifier, "status": "running", "pid": 99999999, "incarnation": "nonexistent"},
    )
    assert jobs.get(identifier)["status"] == "interrupted"


def test_head_to_head_rps_is_simultaneous_zero_sum_and_seeded(tmp_path):
    from evoforge.research.analysis import rps_tournament

    manager = trained(tmp_path, generations=1)
    data = safe_load(manager.path("alpha") / "champion.pt")
    same = [{**data, "experiment": name, "fingerprint": "same"} for name in ("alpha", "beta")]
    result = rps_tournament(same, 12, 3, lambda: None, lambda _: None)
    assert result["rounds_per_match"] == 3
    assert result["seeds"] == [12, 13, 14]
    assert all(
        t["draws"] == 3 and t["wins"] == t["losses"] == 0 for t in result["pairs"][0]["trials"]
    )
    assert sum(r["mean_fitness"] for r in result["results"]) == 0


def test_finished_job_wins_a_liveness_check_race(tmp_path, monkeypatch):
    from evoforge.research import jobs as module

    jobs = Jobs(Supervisor(tmp_path))
    identifier = "b" * 32
    path = jobs.root / identifier
    path.mkdir()
    atomic_json(
        path / "job.json", {"id": identifier, "status": "running", "pid": 42, "incarnation": "old"}
    )

    def exited(_):
        atomic_json(
            path / "job.json",
            {"id": identifier, "status": "completed", "result": {"verified": True}},
        )
        return None

    monkeypatch.setattr(module, "incarnation", exited)
    assert jobs.get(identifier)["status"] == "completed"
    assert jobs.get(identifier)["result"]["verified"]


def test_bookmark_schema_upgrade_preserves_existing_annotations(tmp_path):
    store = ResearchStore(tmp_path)
    store.annotate("Original notes", ["keep"])
    store.bookmark("Original view", "Family Trees", 0, "0:1")
    with store.connect() as db:
        db.execute("ALTER TABLE bookmarks DROP COLUMN right_agent")
        db.execute("PRAGMA user_version=1")
    upgraded = ResearchStore(tmp_path)
    assert upgraded.metadata()["notes"] == "Original notes"
    assert upgraded.bookmarks()[0]["right_agent"] is None
    upgraded.bookmark("Exact pair", "Genetic Comparison", agent="0:1", right_agent="4:2")
    assert upgraded.bookmarks()[0]["right_agent"] == "4:2"


def test_seed_batch_rolls_back_after_reserved_destination_failure(tmp_path, monkeypatch):
    import evoforge.games

    app = create_app(tmp_path)
    client = TestClient(app)
    original = evoforge.games.game_version
    calls = 0

    def fail_second(game):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("Simulated metadata failure")
        return original(game)

    monkeypatch.setattr(evoforge.games, "game_version", fail_second)
    response = client.post(
        "/api/v1/research/batches",
        json={"prefix": "atomic", "seeds": [1, 2], "config": asdict(small())},
    )
    assert response.status_code == 422
    assert not (tmp_path / "atomic-1").exists()
    assert not (tmp_path / "atomic-2").exists()
    assert app.state.supervisor.list() == []


def test_archive_loader_enforces_expanded_tensor_limit(tmp_path):
    path = tmp_path / "expanded.pt"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("archive/data/0", b"0" * 100000)
    assert path.stat().st_size < 4096
    with pytest.raises(ValueError, match="Expanded tensor archive"):
        safe_load(path, max_bytes=4096)


def test_loader_rejects_old_torch_runtime(tmp_path, monkeypatch):
    import torch

    monkeypatch.setattr(torch, "__version__", "2.9.1+cpu")
    with pytest.raises(ValueError, match="PyTorch 2.10"):
        safe_load(tmp_path / "any.pt")


def test_restore_checks_installed_architecture_before_publication(tmp_path):
    from evoforge.policy import Policy

    manager = trained(tmp_path, generations=1)
    path = manager.path("alpha") / "checkpoint.pt"
    data = safe_load(path)
    model = Policy(input_size=9, hidden=6, actions=3)
    data.update(architecture=model.architecture, population=[model.state_dict()] * 3, champion=None)
    save(path, data, backup=False)
    backup = create_backup(manager, "alpha")
    with pytest.raises(ValueError, match="configured environment or network"):
        restore_backup(manager, backup["id"], "incompatible")
    assert not manager.path("incompatible").exists()


def test_backup_rejects_finite_values_that_overflow_policy_dtype(tmp_path):
    from evoforge.research.archive import validate_artifacts

    manager = trained(tmp_path, generations=1)
    path = manager.path("alpha") / "checkpoint.pt"
    data = safe_load(path)
    name = next(iter(data["population"][0]))
    values = data["population"][0][name].double()
    values.flatten()[0] = 1e300
    data["population"][0][name] = values
    save(path, data, backup=False)
    with pytest.raises(ValueError, match="dtype conversion"):
        validate_artifacts(manager.path("alpha"))


def test_backup_checks_research_architecture_without_allocating(tmp_path):
    from evoforge.research.archive import validate_artifacts

    manager = trained(tmp_path, generations=1)
    store = ResearchStore(manager.path("alpha"))
    with store.connect() as db:
        row = db.execute("SELECT descriptor,weights FROM nodes WHERE id='1:0'").fetchone()
        descriptor = json.loads(row["descriptor"])
        descriptor["architecture"]["hidden"] = [1000000000]
        encoded = json.dumps(descriptor)
        fingerprint = hashlib.sha256(encoded.encode() + b"\0" + row["weights"]).hexdigest()
        db.execute(
            "UPDATE nodes SET descriptor=?,fingerprint=? WHERE id='1:0'", (encoded, fingerprint)
        )
    with pytest.raises(ValueError, match="policy dimensions"):
        validate_artifacts(manager.path("alpha"))
