# EvoForge 1.0.0-rc.1

EvoForge trains discrete game agents with evolution, PPO, or hybrid learning.
Install a trusted game plugin, configure an experiment in the Textual SSH UI,
start a detached worker, watch sampled real gameplay, reconnect from another
client, compare interaction budgets, and recover from committed checkpoints.

This is a **release candidate**. Cloud checks and operator acceptance are tracked
in [release validation](docs/RELEASE.md). No stable tag or release is published.

## Quick start (Linux, bash or fish)

```sh
python3 -m venv .venv
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -e '.[dev,tui,api]'
.venv/bin/python -m pip install -e examples/coin-game
.venv/bin/evoforge doctor
.venv/bin/evoforge games validate coin
.venv/bin/evoforge tui --output runs/first
```

In Experiments, create a named run. In Settings, choose Coin, training mode and
population, enter optional hidden widths and plugin JSON, then Validate & Save.
Use Overview to start/pause/resume/stop. Live Training shows actual sampled worker
frames. Champion and Population modes are independent replays with adjustable
speed/focus/density. Closing the UI leaves workers running; reopen the same run
to reconnect. The library supports duplicate/rename/archive, analytics export and
matched environment-step comparisons.

Small headless run:

```sh
.venv/bin/evoforge train --game coin --mode evolution --population 4 --elites 1 --ppo-candidates 0 --generations 3 --hidden-widths 16,8 --output runs/coin-demo
.venv/bin/evoforge experiments inspect coin-demo --root runs
.venv/bin/evoforge experiments export coin-demo --root runs --format csv
```

Use `--background` to return immediately. Use `--resume` with the same output to
resume or extend a run; only generation targets may change. All CLI/TUI/API
worker controls use the same local supervisor and reject duplicate workers.

## Commands

```text
evoforge                         interactive TUI, headless help otherwise
evoforge tui --output runs/demo
evoforge dashboard               standard-library terminal fallback
evoforge games list|inspect|validate [GAME_ID]
evoforge experiments list|create|inspect|compare|duplicate|rename|archive|unarchive|export
evoforge train --game GAME --mode evolution|ppo|hybrid --output runs/demo
evoforge workers list|status|start|recover|pause|resume|stop [ID] --root runs
evoforge api serve --root runs    localhost:8765; remote binding requires token
evoforge migrate CHECKPOINT      dry-run; --apply preserves original backup
evoforge play CHAMPION --fps 7
evoforge baseline GAME --heuristic
evoforge doctor --root runs
evoforge version
```

Each command supports `--help`. Existing Snake/Flappy configs, CSV histories and
compatible v0.9 checkpoints remain readable. New archives use an integrity header
and restricted tensor loading, so external scripts must use `safe_load` rather
than calling `torch.load` directly. Never overwrite your historical run folder
when upgrading; see [migration](docs/training.md#checkpoint-schema-1).

## Documentation

- [Installation, CachyOS, fish, SSH and GTX 1070](docs/installation.md)
- [Game SDK and complete external example](docs/sdk.md)
- [Algorithms, configuration and checkpoint migration](docs/training.md)
- [Supervisor and systemd administration](docs/supervisor.md)
- [Telemetry and spectator protocol](docs/telemetry.md)
- [REST/WebSocket API and authentication](docs/api.md)
- [Textual controls and analytics](docs/tui.md)
- [Architecture, security and troubleshooting](docs/operations.md)
- [Contributing and testing](CONTRIBUTING.md)
- [Release readiness and unverified scenarios](docs/RELEASE.md)
- [Audit and incremental implementation progress](docs/PROGRESS.md)

## Browser control center (Web 0.1)

EvoForge now includes a responsive React control center for experiment lifecycle,
worker controls, measured analytics, plugin discovery and a generic PixiJS spectator.
Snake uses monochrome Nokia Snake II sprites supplied by HelpfulSheep; Flappy
uses the familiar Flappy Bird artwork supplied by FlapPyBird. Source attribution
and exact sprite hashes are included with the assets. The Coin example retains
its original EvoForge artwork.
Sampled episodes are recorded for later playback; champion and population replay
run independently from training. The Textual application remains supported.

```sh
.venv/bin/python -m pip install -e '.[api,tui]' -e ./examples/coin-game
npm --prefix web ci
npm --prefix web run build
.venv/bin/evoforge api serve --root ./runs --host 127.0.0.1 --port 8765
```

Open http://127.0.0.1:8765. For a fresh machine, follow the full
[web development setup](docs/web-development.md). See [production and LAN/SSH access](docs/web-deployment.md),
[security](docs/web-security.md), [render scenes](docs/render-scene.md),
[asset manifests](docs/asset-manifest.md), [Geometry Dash spectator](docs/geometrydash-spectator.md), [replay format](docs/replay-format.md), and
[troubleshooting](docs/web-troubleshooting.md). No public tunnel or automatic deployment is required.
