"""One bounded, detached research job per workspace. No training RNG is touched."""

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid

import torch

from evoforge.core.checkpoints import atomic_json, safe_load, save
from evoforge.supervisor.lifecycle import incarnation
from evoforge.supervisor.manager import Supervisor, WorkerConflict

from .analysis import behavior, benchmark, rps_tournament, snapshot, tournament
from .provenance import environment_identity
from .store import ResearchStore, pack_state


class Cancelled(Exception):
    pass


class Jobs:
    def __init__(self, manager):
        self.manager = manager
        self.root = manager.root / ".research-jobs"
        self.root.mkdir(exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("Research job directory cannot be a symlink")

    def path(self, identifier):
        import re

        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Invalid job identifier")
        path = self.root / identifier
        if path.is_symlink() or not path.is_dir():
            raise KeyError(identifier)
        return path

    def get(self, identifier):
        path = self.path(identifier)
        data = json.loads((path / "job.json").read_text())
        if data["status"] == "running" and incarnation(data.get("pid")) != data.get("incarnation"):
            # The process may have committed its result between our read and the
            # liveness check. A second read after observed exit is authoritative.
            latest = json.loads((path / "job.json").read_text())
            if latest["status"] != "running":
                return latest
            data = latest
            data.update(
                status="interrupted", error="Research process exited before saving a result"
            )
            atomic_json(path / "job.json", data)
        elif data["status"] == "queued" and time.time() - data["created"] > 30:
            data.update(status="interrupted", error="Research process did not start")
            atomic_json(path / "job.json", data)
        return data

    def list(self):
        paths = sorted(
            (p for p in self.root.iterdir() if p.is_dir() and not p.is_symlink()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        result = []
        for path in paths[:100]:
            try:
                result.append(self.get(path.name))
            except (KeyError, ValueError, OSError):
                continue
        return result

    def submit(
        self, kind, experiments, seed=700000, episodes=8, agents=None, protocol="shared_scenarios"
    ):
        from evoforge.trainer import Config

        fd = os.open(self.root / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise WorkerConflict("A research job is already running") from exc
            if len(self.list()) >= 100:
                raise ValueError("Remove old research jobs before creating more (limit 100)")
            runs = [self.manager.inspect(name) for name in experiments]
            if not runs or len(runs) > 8 or len(set(experiments)) != len(experiments):
                raise ValueError("Choose 1–8 different experiments")
            identities = [environment_identity(Config(**r["config"])) for r in runs]
            if any(identity != identities[0] for identity in identities):
                raise ValueError(
                    "Research comparisons require the same game and environment configuration"
                )
            if sum(r["config"]["max_steps"] * episodes for r in runs) > 250000:
                raise ValueError("Requested analysis exceeds 250,000 environment steps")
            if protocol == "rps_head_to_head":
                if kind != "tournament" or any(r["config"]["game"] != "rps" for r in runs):
                    raise ValueError("Head-to-head tournaments require RPS experiments")
                rounds = min(
                    runs[0]["config"]["max_steps"],
                    runs[0]["config"].get("game_config", {}).get("horizon", 23),
                )
                if len(runs) * (len(runs) - 1) * episodes * rounds > 250000:
                    raise ValueError("Head-to-head tournament exceeds 250,000 agent decisions")
            inputs = []
            for run, identity in zip(runs, identities):
                if kind == "backup":
                    break
                store = ResearchStore(self.manager.path(run["id"]))
                recorded = store.metadata().get("manifest", {}).get("environment")
                if recorded and recorded != identity:
                    raise ValueError(
                        "Current environment differs from the experiment's recorded environment"
                    )
                if kind == "behavior":
                    if len(runs) != 1 or not agents or len(agents) != 2:
                        raise ValueError("Choose two retained agents from one experiment")
                    inputs = [snapshot(store, agent, run["config"]) for agent in agents]
                    break
                champion = self.manager.path(run["id"]) / "champion.pt"
                if not champion.is_file():
                    raise ValueError(f"{run['id']}: no champion is available")
                if champion.stat().st_size > 32 * 1024 * 1024:
                    raise ValueError("Champion exceeds analysis size limit")
                data = safe_load(champion, max_bytes=32 * 1024 * 1024)
                _, _, digest = pack_state(data["state_dict"], data["architecture"])
                inputs.append({**data, "experiment": run["id"], "fingerprint": digest})
            identifier = uuid.uuid4().hex
            path = self.root / identifier
            path.mkdir()
            request = {
                "kind": kind,
                "protocol": protocol,
                "experiments": experiments,
                "seed": seed,
                "episodes": episodes,
                "environment": identities[0],
                "agents": agents,
                "inputs": len(inputs),
            }
            hashes = []
            for i, data in enumerate(inputs):
                name = path / f"input-{i}.pt"
                save(name, data, backup=False)
                hashes.append(hashlib.sha256(name.read_bytes()).hexdigest())
            request["input_sha256"] = hashes
            atomic_json(path / "request.json", request)
            job = {
                "id": identifier,
                "kind": kind,
                "experiments": experiments,
                "status": "queued",
                "created": time.time(),
                "progress": 0,
                "request": request,
            }
            atomic_json(path / "job.json", job)
            try:
                with (path / "process.log").open("w") as log:
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "evoforge.research.jobs",
                            "--root",
                            str(self.manager.root),
                            "--job",
                            identifier,
                            "--lock-fd",
                            str(fd),
                        ],
                        pass_fds=(fd,),
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                        close_fds=True,
                        env={**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
                    )
            except Exception:
                atomic_json(
                    path / "job.json",
                    {**job, "status": "failed", "error": "Could not launch research process"},
                )
                raise
            return job
        finally:
            os.close(fd)

    def cancel(self, identifier):
        data = self.get(identifier)
        if data["status"] not in {"queued", "running"}:
            raise WorkerConflict("Job has already finished")
        (self.path(identifier) / "cancel").touch()
        return {"requested": True}

    def delete(self, identifier):
        import shutil

        if self.get(identifier)["status"] in {"queued", "running"}:
            raise WorkerConflict("Cancel the job and wait for it to finish before removing it")
        shutil.rmtree(self.path(identifier))


def run(root, identifier, lock_fd):
    jobs = Jobs(Supervisor(root))
    path = jobs.path(identifier)
    job = json.loads((path / "job.json").read_text())
    job.update(status="running", pid=os.getpid(), incarnation=incarnation(os.getpid()))
    atomic_json(path / "job.json", job)
    request = job["request"]
    started, checks = time.monotonic(), 0
    torch.set_num_threads(1)

    def check():
        nonlocal checks
        checks += 1
        if (path / "cancel").exists():
            raise Cancelled("Cancelled by user")
        if time.monotonic() - started > 180 or checks > 250000:
            raise ValueError("Research time/step budget exhausted")

    def progress(value):
        check()
        job["progress"] = value
        atomic_json(path / "job.json", job)

    try:
        check()
        inputs = []
        for i, digest in enumerate(request["input_sha256"]):
            file = path / f"input-{i}.pt"
            if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
                raise ValueError("Research input fingerprint mismatch")
            inputs.append(safe_load(file, max_bytes=512 * 1024 * 1024))
        if request["kind"] == "tournament":
            evaluator = (
                rps_tournament if request.get("protocol") == "rps_head_to_head" else tournament
            )
            result = evaluator(inputs, request["seed"], request["episodes"], check, progress)
        elif request["kind"] == "behavior":
            result = behavior(inputs, request["seed"], check)
        elif request["kind"] == "benchmark":
            result = benchmark(inputs[0], check)
        elif request["kind"] == "backup":
            from .archive import create_backup

            result = create_backup(jobs.manager, request["experiments"][0], check)
        else:
            raise ValueError("Unknown research job")
        check()
        job.update(status="completed", progress=1, result=result)
    except Cancelled as exc:
        job.update(status="cancelled", error=str(exc))
    except Exception as exc:
        job.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        job["finished"] = time.time()
        atomic_json(path / "job.json", job)
        os.close(lock_fd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--lock-fd", type=int, required=True)
    args = parser.parse_args()
    run(args.root, args.job, args.lock_fd)
