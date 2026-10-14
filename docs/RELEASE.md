# EvoForge 1.0.0-rc.1 release validation

This release candidate is subject to operator acceptance. Do not merge, create a
stable v1.0.0 tag or publish a GitHub release before explicit final authorization.

## Implemented scope

Installed GamePlugin SDK/validation with external Coin example; configurable
actor-critic MLPs; evolution/PPO/hybrid with separate fitness/rewards; versioned
integrity-checked checkpoints; durable SQLite supervisor and metrics; real
sampled gameplay frames; Textual controls, plugin/worker browser and analytics;
versioned authenticated REST/WebSocket API; CLI, doctor, migrations, docs and CI.

Final local full suite: **68 passed, 1 upstream warning in 50.82s** on Python
3.12.14 / CPU torch 2.14.1. Clean wheel installation independently completed all
three external-plugin training modes, checkpoint/frame checks, API schema and
Textual startup. Lint, formatting, wheel/sdist builds and archive checks passed.
See PROGRESS.md for exact commands, per-stage commits and evidence.

| Acceptance scenario | Cloud evidence | Remaining gate |
| --- | --- | --- |
| Clean install and external entry-point discovery | Passed in isolated wheel venv | Operator host installation |
| External evolution / PPO / hybrid | Passed with 4 inputs, 2 actions | Longer benchmark quality assessment |
| Disconnect survival | Real parent-exit + SIGHUP passed | Actual SSH logout policy |
| Second client and pause/resume/stop | Real process and Textual controls passed | Real SSH terminal interaction |
| Live frames into Textual | Actual evaluation frames passed | Native terminal rendering |
| API controls and authentication | In-process and real TCP/WS passed | Remote TLS/SSH forwarding setup |
| Checkpoint interruption and recovery | SIGKILL, corruption, RNG/optimizer resume passed | Host reboot/systemd test |
| Existing Snake / Flappy runs | Pinned v0.9 runs resumed with backups | Operator historical dataset sample |
| Analytics, export and comparison | Passed at matched step budgets | Operator workload scaling |
| Automated UI/API/full suite | 3 Textual, 4 API/transport, 68 total passed | Remote Python 3.10–3.13 CI |
| GTX 1070 | CPU fallback and doctor implemented | Actual CUDA kernel/driver validation |

## Compatibility

Actual Snake and Flappy v0.9 runs are generated from pinned baseline 938b597 in
tests, then inspected and resumed by the new implementation. Legacy config/CSV
columns and two-layer state keys remain compatible. Restricted legacy loading
rejects unsafe pickle payloads. New `.pt` files require EvoForge's safe_load
reader. Format conversion has a dry-run and preserves an original backup. Only
generation targets may change during resume. Unknown schemas, plugin versions
and architectures fail explicitly. Missing historic interaction/optimizer counts
cannot be reconstructed. Preserve runs/ on upgrades.

## Operator acceptance checklist (unverified in Codex Cloud)

Use a new temporary acceptance runs root, never production experiment data.

- [ ] Install wheel in a fresh supported Linux Python venv and run doctor.
- [ ] On CachyOS/fish, install the reviewed external example; validate and train
  evolution, PPO and hybrid with `--game coin --population 4 --elites 1`.
- [ ] Start a longer worker from Textual; confirm Live Training shows moving Coin,
  Snake and Flappy frames and that replay controls/locking behave in a real terminal.
- [ ] Record worker identity and generation, disconnect SSH fully, log in again,
  and confirm generation advanced with the same worker identity. Test host logout
  policy with and without systemd user lingering.
- [ ] Open a second TUI and API client pointing to the same root; pause, wait for
  PAUSED, verify no new generation; resume and stop; duplicate start must conflict.
- [ ] Install the documented systemd service using absolute paths and a mode-600
  token EnvironmentFile. Verify API restart leaves worker alive and boot recovery
  marks old jobs failed until explicitly recovered. Actual host restart required.
- [ ] Verify missing/wrong API credentials yield 401 and unauthenticated WS closes
  during the handshake (application code 4401 / HTTP 403). Prefer SSH forwarding; test TLS proxy if remote binding is needed.
- [ ] Stop a test-owned worker abruptly after verifying its incarnation; restart
  from checkpoint and confirm unique generation metrics. Corrupt only the test
  primary and confirm backup recovery. Restore original test files afterward.
- [ ] Compare two runs at matched environment-step budget, export CSV/JSON and
  export/play the saved champion; distinguish validation from withheld test.
- [ ] On GTX 1070, run doctor and inspect actual CUDA kernel result. Keep CPU
  execution unless the GPU path is explicitly validated (training remains CPU).
- [ ] Review CI Python 3.10–3.13 checks and artifacts; final acceptance must pass
  before changing 1.0.0rc1 to stable.

## Known boundaries

Flattened numeric Box observations and zero-based discrete actions only. CPU
training; optional graphical viewer remains Snake-only. Telemetry is bounded and
lossy. Checkpoint history/lineage and CSV materialization scale with run length;
large-run performance is not certified. Interaction budgets stop at generation
boundaries and can overshoot. Worker recovery after reboot is explicit. Plugin
code is trusted and can block cooperative controls. The local API is a
single-operator service; it is not a multi-tenant sandbox. Real SSH, systemd,
real-terminal rendering and GTX 1070 behavior require the procedures above.
