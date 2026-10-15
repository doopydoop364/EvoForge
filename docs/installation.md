# Installation and upgrades

Linux is the primary supported supervisor platform (/proc identity + flock).
Python >=3.10 is required. Compatibility CI targets 3.10–3.13. Cloud validation is
on Python 3.12; CI results and operator validation are separate acceptance gates.
Basic training depends on NumPy, PyTorch and Gymnasium. Textual, API and graphical
Snake viewer are optional extras. Training always runs on CPU in this release.

## CachyOS / Arch

```sh
sudo pacman -S --needed python python-pip git
git clone https://github.com/doopydoop364/EvoForge.git
cd EvoForge
git switch feature/v1.0-universal-core
python -m venv .venv
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -e '.[tui,api]'
.venv/bin/evoforge doctor
```

Explicit `.venv/bin/...` commands work in fish without activation. Use
`source .venv/bin/activate.fish` if desired. Never use sudo pip or replace the
system Python. Standard Linux desktops follow the same venv steps; install your
distribution's Python/venv/git packages first.

## Headless server and SSH

Install `-e .` for CLI training, `-e '.[tui]'` for terminal administration,
`-e '.[api]'` for HTTP/WebSocket access. No display server or pygame is required.
Use `ssh -t user@host` for an interactive TUI. UTF-8 terminals of 80x24 or larger
are recommended; 120x40 gives room for multiple spectator panels.

Workers detach from the SSH session. For logout policies that kill user cgroups,
use the [systemd user service and lingering](supervisor.md), then start workers
through its API. Validate actual logout behavior on your host before unattended
runs. A new TUI or API client must use the same absolute runs root.

## NVIDIA GTX 1070

The GTX 1070 is Pascal (SM 6.1). Some modern CUDA torch builds do not include its
kernels. `doctor` reports device capability, compiled architectures and executes
a small CUDA matrix multiplication if a GPU is visible. Detection alone is not a
passing kernel check. The supported training path is CPU, even if CUDA works.
CPU-only torch installation avoids mandatory NVIDIA runtime dependencies. Do not
change driver/toolkit installations based solely on an availability flag.

## External games and development

```sh
.venv/bin/python -m pip install -e '.[dev,tui,api]'
.venv/bin/python -m pip install -e examples/coin-game
.venv/bin/evoforge games list
.venv/bin/evoforge games validate coin
```

Explicit plugin installation grants Python execution. Review plugin source and
its dependencies. There is no arbitrary-code upload endpoint.

## Upgrade existing v0.9 runs

Back up the entire runs root while workers are stopped. Upgrade code on the
feature branch and reinstall. Keep config.json, metrics.csv, checkpoint.pt/.bak,
champion.pt, spectator.pt and worker.json in place. Run `evoforge migrate PATH`
first for a storage-format dry-run. `--apply` preserves `.v090-original`; do not
apply repeatedly. New-format writing preserves the previous valid archive.
Resume allows a larger generation target but rejects incompatible game versions,
network architecture or training settings. Review `docs/training.md` for legacy
counter limitations and checksum behavior.

## Test the v1.0 experiment-action fix before merge

In an existing Git clone, stop workers before renaming/archiving experiments and
back up the entire runs root, including its hidden `.evoforge.sqlite` metadata.
Close the old TUI, then install the bugfix branch in the same virtual environment:

```sh
git fetch origin
git switch bugfix/v1.0-experiment-actions
git pull --ff-only origin bugfix/v1.0-experiment-actions
.venv/bin/python -m pip install -e '.[tui,api]'
.venv/bin/evoforge tui --output /absolute/path/to/existing/runs/EXPERIMENT
```

Replace the final path with an existing experiment directory, keeping the same
runs root used previously. The commands work in fish without activation. No
experiment migration, reset or deletion is needed for this fix. This branch is
a review build, not a merged release. After the PR is approved and merged, use
`feature/v1.0-universal-core` instead of the bugfix branch in the commands above.

## Web interface

See [web development](web-development.md) for Node/Python setup and
[deployment](web-deployment.md) for production, CachyOS/fish and secure access from
another machine. Install the optional Coin package to expose that example in the UI.
