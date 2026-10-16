"""Worker executable, independent of TUI/API/SSH client process lifetime."""

import argparse
import fcntl
import json
import os
import signal
import threading
import time
import traceback

from evoforge.core.checkpoints import atomic_json
from evoforge.trainer import TrainingStopped

from .lifecycle import incarnation, transition
from .manager import Supervisor


def run_worker(root, experiment, identity, lock_fd):
    manager = Supervisor(root)
    database = manager.database
    path = manager.path(experiment)
    # Inherited open file description holds the same exclusive lock after parent exit.
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stop = threading.Event()
    paused = threading.Event()
    finish = threading.Event()
    failed = []
    trainer = None
    publisher = None

    def signal_stop(*_):
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, signal_stop)
    # Detached worker ignores terminal hangups. Control is cooperative, no client PID signals.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    def heartbeat():
        while not finish.is_set():
            try:
                with database.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute(
                        "SELECT * FROM workers WHERE experiment=?", (experiment,)
                    ).fetchone()
                    if not row or row["identity"] != identity:
                        raise RuntimeError("Worker ownership lost")
                    request = row["request"]
                    state = db.execute(
                        "SELECT status FROM experiments WHERE id=?", (experiment,)
                    ).fetchone()["status"]
                    if request == "stop" or stop.is_set():
                        if state in ("STARTING", "RUNNING", "PAUSED"):
                            transition(db, experiment, "STOPPING")
                        stop.set()
                        paused.clear()
                    elif request == "pause":
                        paused.set()
                    elif request == "resume":
                        paused.clear()
                        if state == "PAUSED":
                            transition(db, experiment, "RUNNING")
                    db.execute(
                        "UPDATE workers SET heartbeat=?,pid=?,incarnation=?,request=NULL WHERE experiment=? AND identity=?",
                        (time.time(), os.getpid(), incarnation(os.getpid()), experiment, identity),
                    )
                    current = db.execute(
                        "SELECT status FROM experiments WHERE id=?", (experiment,)
                    ).fetchone()["status"]
                atomic_json(
                    path / "worker.json",
                    {
                        "pid": os.getpid(),
                        "identity": identity,
                        "incarnation": incarnation(os.getpid()),
                        "state": current.lower(),
                        "generation": trainer.generation if trainer else 0,
                        "updated_at": time.time(),
                    },
                )
            except Exception as exc:
                failed.append(exc)
                stop.set()
                return
            finish.wait(0.2)

    def control():
        if paused.is_set():
            with database.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                state = db.execute(
                    "SELECT status FROM experiments WHERE id=?", (experiment,)
                ).fetchone()["status"]
                if state == "RUNNING":
                    transition(db, experiment, "PAUSED")
        while paused.is_set() and not stop.is_set():
            finish.wait(0.05)
        if stop.is_set():
            raise TrainingStopped()

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    final = "FAILED"
    try:
        from evoforge.trainer import Config, Trainer

        cfg = Config(**json.loads((path / "config.json").read_text()))
        from evoforge.telemetry import TrainingPublisher

        publisher = TrainingPublisher(path, cfg.game, identity)
        trainer = Trainer(
            cfg,
            path,
            resume=(path / "checkpoint.pt").exists(),
            control=control,
            telemetry=publisher,
            managed=True,
        )
        trainer.on_commit = lambda current: database.sync_metrics(experiment, current.history)
        trainer.on_commit(trainer)
        with database.connect() as db:
            state = db.execute(
                "SELECT status FROM experiments WHERE id=?", (experiment,)
            ).fetchone()["status"]
            if state == "STARTING":
                transition(db, experiment, "RUNNING")
        control()
        result = trainer.run()
        if failed:
            raise RuntimeError(f"Heartbeat failed: {failed[-1]}")
        final = "STOPPED" if result == "stopped" else "COMPLETED"
    except TrainingStopped:
        final = "STOPPED"
    except Exception as exc:
        traceback.print_exc()
        with database.connect() as db:
            db.execute(
                "UPDATE workers SET error=? WHERE experiment=? AND identity=?",
                (str(exc), experiment, identity),
            )
    finally:
        if publisher:
            publisher.close()
        finish.set()
        thread.join(timeout=6)
        with database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT status FROM experiments WHERE id=?", (experiment,)
            ).fetchone()["status"]
            if final == "STOPPED" and current != "STOPPING":
                transition(db, experiment, "STOPPING")
            if final == "COMPLETED" and current == "STOPPING":
                final = "STOPPED"
            transition(db, experiment, final)
            db.execute(
                "UPDATE workers SET heartbeat=?,generation=? WHERE experiment=? AND identity=?",
                (time.time(), trainer.generation if trainer else 0, experiment, identity),
            )
            atomic_json(
                path / "worker.json",
                {
                    "pid": os.getpid(),
                    "identity": identity,
                    "incarnation": incarnation(os.getpid()),
                    "state": final.lower(),
                    "generation": trainer.generation if trainer else 0,
                    "updated_at": time.time(),
                },
            )
            # Publish terminal status only after file writes and lock release. A
            # new owner can acquire the lock but must wait for this transaction.
            os.close(lock_fd)
    return 0 if final != "FAILED" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--lock-fd", type=int, required=True)
    args = parser.parse_args()
    raise SystemExit(run_worker(args.root, args.experiment, args.identity, args.lock_fd))


if __name__ == "__main__":
    main()
