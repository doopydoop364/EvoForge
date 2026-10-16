import json
import os
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from evoforge.storage import Database
from evoforge.supervisor import Supervisor, WorkerConflict
from evoforge.supervisor.lifecycle import incarnation, transition
from evoforge.trainer import Config


def wait_state(manager, name, states, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = manager.inspect(name)
        if row["status"] in states:
            return row
        if row["status"] == "FAILED" and "FAILED" not in states:
            pytest.fail(
                f"Worker failed: {row}; {(manager.path(name) / 'training.log').read_text()}"
            )
        time.sleep(0.03)
    pytest.fail(f"Timed out waiting for {states}: {manager.inspect(name)}")


def long_config():
    return Config(
        game="coin",
        mode="ppo",
        population=2,
        elites=1,
        ppo_candidates=0,
        generations=10000,
        hidden=8,
        eval_episodes=1,
        ppo_episodes=1,
        game_config={"horizon": 20},
    )


def test_real_worker_reconnect_pause_resume_stop_and_duplicates(tmp_path):
    manager = Supervisor(tmp_path)
    manager.create("demo", long_config())
    manager.start("demo")
    try:
        wait_state(manager, "demo", {"RUNNING"})
        second = Supervisor(tmp_path)
        assert (
            second.inspect("demo")["worker"]["identity"]
            == manager.inspect("demo")["worker"]["identity"]
        )
        with pytest.raises(WorkerConflict):
            second.start("demo")
        second.request("demo", "pause")
        paused = wait_state(second, "demo", {"PAUSED"})
        generation = paused["worker"]["generation"]
        time.sleep(0.3)
        assert second.inspect("demo")["worker"]["generation"] == generation
        second.request("demo", "resume")
        wait_state(second, "demo", {"RUNNING"})
        second.request("demo", "stop")
        wait_state(second, "demo", {"STOPPED"})
        assert (tmp_path / "demo" / "checkpoint.pt").exists()
        second.start("demo")
        wait_state(second, "demo", {"RUNNING"})
        second.request("demo", "stop")
        wait_state(second, "demo", {"STOPPED"})
    finally:
        if manager.inspect("demo")["status"] in {"RUNNING", "PAUSED", "STARTING"}:
            manager.request("demo", "stop")
            wait_state(manager, "demo", {"STOPPED"})


def test_concurrent_clients_cannot_duplicate(tmp_path):
    manager = Supervisor(tmp_path)
    manager.create("race", long_config())

    def start():
        try:
            return Supervisor(tmp_path).start("race")["worker"]["identity"]
        except WorkerConflict:
            return None

    with ThreadPoolExecutor(2) as pool:
        identities = list(pool.map(lambda _: start(), range(2)))
    try:
        assert sum(x is not None for x in identities) == 1
        wait_state(manager, "race", {"RUNNING"})
    finally:
        manager.request("race", "stop")
        wait_state(manager, "race", {"STOPPED"})


def test_crash_identity_and_recovery(tmp_path):
    manager = Supervisor(tmp_path)
    manager.create("crash", long_config())
    manager.start("crash")
    running = wait_state(manager, "crash", {"RUNNING"})
    pid = running["worker"]["pid"]
    # Test-owned worker; identity verified before deliberately injecting crash.
    assert incarnation(pid) == running["worker"]["incarnation"]
    os.kill(pid, signal.SIGKILL)
    manager.children["crash"].wait(timeout=10)
    wait_state(manager, "crash", {"FAILED"}, timeout=10)
    manager.start("crash")
    try:
        wait_state(manager, "crash", {"RUNNING"})
    finally:
        manager.request("crash", "stop")
        wait_state(manager, "crash", {"STOPPED"})


def test_stale_worker_and_pid_reuse_never_signal(tmp_path, monkeypatch):
    manager = Supervisor(tmp_path)
    manager.create("stale", long_config())
    with manager.database.connect() as db:
        transition(db, "stale", "QUEUED")
        transition(db, "stale", "STARTING")
        transition(db, "stale", "RUNNING")
        db.execute(
            "INSERT INTO workers(experiment,identity,pid,incarnation,heartbeat) VALUES(?,?,?,?,?)",
            ("stale", "old", os.getpid(), "different-boot:1", time.time() - 60),
        )
    monkeypatch.setattr(os, "kill", lambda *_: pytest.fail("Client must never signal a PID"))
    assert manager.inspect("stale")["status"] == "FAILED"
    with pytest.raises(WorkerConflict):
        manager.request("stale", "stop")
    with manager.database.connect() as db:
        with pytest.raises(ValueError, match="Invalid worker transition"):
            transition(db, "stale", "PAUSED")


def test_database_migration_idempotent_and_path_rejection(tmp_path):
    first = Database(tmp_path)
    Database(tmp_path)
    with first.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
    manager = Supervisor(tmp_path)
    for name in ["../escape", "/tmp/escape", ".", "x/y"]:
        with pytest.raises(ValueError):
            manager.path(name)


def test_worker_survives_launching_client_exit_and_hangup(tmp_path):
    manager = Supervisor(tmp_path)
    manager.create("detach", long_config())
    result = subprocess.run(
        [
            str(Path(os.sys.executable)),
            "-c",
            'from evoforge.supervisor import Supervisor; import sys; Supervisor(sys.argv[1]).start("detach")',
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    try:
        running = wait_state(manager, "detach", {"RUNNING"})
        pid = running["worker"]["pid"]
        assert os.getsid(pid) == pid
        os.kill(pid, signal.SIGHUP)
        time.sleep(0.3)
        assert manager.inspect("detach")["status"] == "RUNNING"
    finally:
        manager.request("detach", "stop")
        wait_state(manager, "detach", {"STOPPED"})


def test_stop_during_worker_startup_is_graceful(tmp_path):
    manager = Supervisor(tmp_path)
    manager.create("early-stop", long_config())
    manager.start("early-stop")
    manager.request("early-stop", "stop")
    row = wait_state(manager, "early-stop", {"STOPPED"})
    assert not row["worker"]["error"]


pytestmark = pytest.mark.integration


def test_terminal_status_is_published_after_worker_lock_release(tmp_path, monkeypatch):
    from evoforge.supervisor import worker

    manager = Supervisor(tmp_path)
    config = long_config()
    config.generations = 1
    manager.create("ordering", config)
    fd = os.open(tmp_path / "ordering" / ".worker.lock", os.O_CREAT | os.O_RDWR, 0o600)
    identity = manager._claim("ordering", fd)
    original_close = os.close
    observed = []

    def close(descriptor):
        if descriptor == fd:
            with manager.database.connect() as db:
                status = db.execute(
                    "SELECT status FROM experiments WHERE id='ordering'"
                ).fetchone()["status"]
            metadata = json.loads((tmp_path / "ordering" / "worker.json").read_text())
            observed.append((status, metadata["state"]))
        return original_close(descriptor)

    monkeypatch.setattr(worker.signal, "signal", lambda *_: None)
    monkeypatch.setattr(worker.os, "close", close)
    assert worker.run_worker(tmp_path, "ordering", identity, fd) == 0
    assert observed == [("RUNNING", "completed")]
    assert manager.inspect("ordering")["status"] == "COMPLETED"


def test_historical_metadata_inspectable_when_plugin_uninstalled(tmp_path):
    manager = Supervisor(tmp_path)
    path = tmp_path / "historic"
    path.mkdir()
    (path / "config.json").write_text(
        json.dumps({"game": "not-installed-anymore", "mode": "evolution"})
    )
    manager.register("historic")
    assert manager.inspect("historic")["game_version"] == "unavailable"
    assert manager.list()[0]["id"] == "historic"
