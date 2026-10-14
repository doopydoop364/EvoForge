# EvoForge v0.9.0

EvoForge is a local neuroevolution and PPO experiment runner with a Textual terminal control center.

## v0.9.0

### Implemented

- **Live worker spectating:** the Textual Spectator tab watches `spectator.pt` as the trainer atomically publishes a fresh top-policy sample each generation. Existing champion and replay behavior remains available.
- **Richer analytics:** each new generation records median and standard deviation of fitness, best-to-mean gap, and a population score-spread indicator in `metrics.csv`; the new `RunService` exposes a UI-independent JSON-friendly snapshot and trend summary.
- **SSH disconnect resilience:** both terminal frontends launch training in a separate process session, write output to `training.log`, and training records its PID/state/generation to `worker.json`. A generation checkpoint is written before the worker reports completion.
- **Checkpoint recovery:** each checkpoint replacement retains the prior checkpoint as `checkpoint.pt.bak`; resume falls back to it if the current checkpoint cannot be read. This can lose the most recent completed generation, but preserves earlier progress.
- **Compatibility:** existing `checkpoint.pt`, `champion.pt`, `spectator.pt`, and older `metrics.csv` files remain readable. New metric columns are appended for newly trained generations.
- **Theme persistence:** retained from v0.8.4.

### Incomplete / limitations

- Live snapshots are sampled at generation boundaries, not streamed per episode or step.
- The UI that started a worker can pause/stop it. Reconnecting to a new UI can inspect `worker.json` and logs, but does not yet attach controls to or safely stop that pre-existing worker.
- Worker status can show `stale` after a crash or host reboot; resume from the last valid checkpoint to continue.
- Recovery keeps one previous checkpoint only. Corruption of both checkpoint files requires an external backup.
- `population_diversity` is a score-spread proxy, not a genotype-distance measure.
- The service module is an in-process API foundation; no HTTP server or web frontend is included.

## Install or migrate on the SSH host (fish shell)

On your Mac, copy the archive to the host:

```fish
scp ~/Downloads/EvoForge-v0.9.0.zip iuselinuxbtw@10.0.0.242:~/
ssh iuselinuxbtw@10.0.0.242
```

On the host, save a copy of the current project and unpack v0.9.0:

```fish
cd ~/EvoForge
cp -a . ../EvoForge-v0.8.4-backup
unzip ~/EvoForge-v0.9.0.zip -d /tmp/evoforge-v090
cp -a /tmp/evoforge-v090/EvoForge-v0.9.0/. ~/EvoForge/
.venv/bin/python -m pip install -e '.[dev,tui]'
.venv/bin/python -m pytest -q
```

The package install may need network access if dependencies are not already present. The archive does not contain or overwrite `runs/`; keep that directory in place for run migration.

Start the existing run in the Textual app:

```fish
.venv/bin/evoforge tui --output runs/snake-500
```

Or resume from a shell and let it continue after SSH disconnect:

```fish
nohup .venv/bin/evoforge train --output runs/snake-500 --resume > runs/snake-500/training.log 2>&1 < /dev/null &
disown
```

The Textual and classic dashboard Start actions already create a separate worker session and save logs to the run folder. Use `tail -f runs/snake-500/training.log` to inspect output after reconnecting. Training checkpoints are saved at completed generation boundaries; stopping mid-generation resumes from the prior checkpoint.
