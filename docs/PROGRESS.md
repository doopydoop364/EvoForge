# EvoForge 1.0 release candidate progress

## Baseline audit (2026-10-14)

Baseline: `938b597`, branch `work`; clean tracked tree. Read all source modules,
existing tests and package metadata. Python requirement >=3.10; cloud Python
3.12.14, CPU torch 2.14.1, Textual 8.2.8. Default Python lacks pytest; use `.venv`.

`.venv/bin/python -m pytest -q`: **34 passed, 1 failed** in 3.79s.
Failure: Textual replay timer accesses unmounted #board during app shutdown.

Concrete compatibility defects:
- PPO-only refinement omits game argument, so Flappy learners train on Snake.
- Trainer/replay constructors assume 17 observations and 3 actions.
- Registry is static, fitness assumes board exploration for every game.
- Loading checkpoints uses unrestricted pickle; no schema/architecture metadata.
- Metrics append precedes checkpoint commit, allowing duplicate generations.
- Workers lack locks, durable control requests and PID incarnation checks.
- Textual reload replaces locked champion automatically on each snapshot.
- Package version 0.9.0 disagrees with module version 0.8.4.

Preserve flat public modules and legacy four-tuple environments through adapters;
introduce SDK boundaries without unnecessary package moves. New functionality
must be independently testable without FastAPI or Textual imports in the engine.

## Stages

1. SDK and policy factory: implemented. Installed external coin plugin;
   `.venv/bin/python -m pytest -q tests/test_sdk.py tests/test_games.py tests/test_core.py`: 13 passed.
   Discovery, validation, multidimensional observations, architecture rejection tested.
2. Algorithms/checkpoints: implemented; external evolution/PPO/hybrid and exact
   PPO optimizer/RNG resume verified. Restricted legacy reader, checksums, atomic
   commits, corrupt-primary fallback and metric reconciliation tested.
   Stage checks: 30 passed (training v1, SDK, core, games, service, rewards).
3. Persistent supervisor: implemented. Six real process tests passed in 16.54s:
   startup, second-client controls, pause/resume/stop, duplicate races, SIGKILL
   recovery, stale/PID identity rejection and launching-client exit + SIGHUP.
   Actual SSH logout and systemd remain operator acceptance scenarios.
4. Live telemetry: implemented bounded SQLite WAL ring, nonblocking drop policy,
   actual evaluation frames, independent replay modes and Textual live consumer.
   Telemetry + baseline Textual tests: 3 passed. Baseline shutdown race fixed by
   guarding timer access after DOM removal; champion auto-reload removed.
5. API: implemented versioned typed routes, bearer authentication, remote-bind
   guard, supervisor CRUD/control, event and live frame reconnect cursors. Three
   API integration tests passed (including real worker controls and WebSockets).
   New FastAPI/Starlette emits one upstream httpx deprecation warning.
6. Analytics, Textual, documentation and release checks: implemented.
   Final local verification passed; operator-only acceptance remains open.

No stable release/tag is authorized. Keep 1.0.0rc1 until operator acceptance.

## Operator integration and validation

Stage 6 implementation includes shared supervisor controls in both terminal UIs,
plugin/worker tabs, configurable widths/plugin JSON/mutation/budget forms,
comparison/export controls, locked replays, responsive action grids and focus
borders. Pilot tests exercise creation, invalid and valid submission, duplication,
rename/archive, theme persistence, real start/pause/resume/stop, actual live frames,
all three spectator modes and second-client reconnection after UI shutdown.

CLI now has games, experiments, workers, API, doctor, migration, baseline and
version commands; headless default gives help. GPU doctor executes a CUDA kernel
when available instead of trusting availability alone. Training remains CPU.

Final full suite: **68 passed, 1 warning in 50.82s**
(`.venv/bin/python -m pytest -q`). The warning is upstream Starlette's httpx
TestClient deprecation. Includes regression coverage for incomplete legacy CSV
rows/scientific notation and metadata for an uninstalled external plugin.
Marker collection verifies 16 integration tests, 3 Textual interaction tests,
and 49 remaining unit/engine tests. All are included in the full-suite result.

Real TCP transport integration starts a separate Uvicorn server, rejects missing
HTTP credentials, streams frames over a real WebSocket and exports a champion.
Legacy tests execute pinned v0.9 source for Snake and Flappy, then load/resume each
with the new reader while preserving the original as the backup.

Clean environment validation:

- `uv venv /tmp/evoforge-rc-clean --python .venv/bin/python`
- Installed CPU torch 2.14.1+cpu, built wheel with tui/api extras and the example
  package, with no system-site-packages and no editable EvoForge installation.
- Imported from the clean venv site-packages outside the repository.
- External Coin evolution/PPO/hybrid each completed one supervised generation,
  with measured interaction counts 56 / 64 / 84, each producing 15 real frames.
- Checkpoint loading, optional API OpenAPI generation and Textual startup passed.
- `uv pip check --python /tmp/evoforge-rc-clean/bin/python`: 38 packages compatible.
- `.venv/bin/python -m build`: wheel and sdist passed.
- Ruff lint/format and `git diff --check` passed.

CI defines Python 3.10–3.13 unit jobs plus separate real integration, Textual and
package/quality jobs. These jobs are configured; do not infer remote results from
local testing. No actual SSH logout, systemd user service, host reboot, real
terminal or GTX 1070 test was available. Reproducible operator procedures and
known scaling/format boundaries are in RELEASE.md.


## Reviewable commits

| Commit | Change |
| --- | --- |
| f4fb88e | Game SDK, entry points, example plugin and policy factory |
| 4649cad | Generic algorithms, PPO fix and safe checkpoint schema/recovery |
| a0a62c5 | Durable supervisor, identities, locks and lifecycle controls |
| 516b47f | Bounded actual gameplay telemetry and replay modes |
| 167f10f | Authenticated REST/WebSocket API |
| 7ebdbe8 | Terminal workflows, analytics, CLI, docs, CI and release checks |

Development branch: https://github.com/doopydoop364/EvoForge/tree/feature/v1.0-universal-core

No stable tag/release or merge has been performed. Package version is PEP 440
`1.0.0rc1` (displayed in documentation as 1.0.0-rc.1). All requested implementation
stages are present; the outstanding release gates are the operator acceptance
items in RELEASE.md and remote CI results, not claims established by cloud mocks.

## RC1 spectator and action-layout stabilization

Focused follow-up to CachyOS/Konsole testing; package remains 1.0.0rc1.

Root causes reproduced against e3ba767:

- Opening a run unconditionally loaded a champion and painted its missing-file
  message before changing an internal mode flag to live.
- Load champion changed the internal mode without updating the selector, leaving
  a visible Live Training selection that no longer polled real telemetry.
- Live polling returned silently without replacing replay/empty content when no
  database/frames existed, and left stale champion detail content behind.
- Population replay unnecessarily depended on loading the champion first.
- Every telemetry poll initialized writer pragmas/schema and swallowed storage
  errors, obscuring a failed read.
- One fixed three-column grid sized every action group alike, placed the run-name
  input in a button cell, and provided no narrow/short-terminal scrolling plan.

The worker path was verified: Trainer evaluation callbacks -> TrainingPublisher
-> per-experiment bounded SQLite WAL ring -> read-only frame query -> Textual.
No artificial gameplay frames or reward/training changes were introduced.

Fixes centralize mode selection, use independent shared Replay loaders, reset
run-specific replay/frame state, and show distinct mode/lifecycle empty states
and visible read errors. Completed runs retain accessible recorded frames. Reusable
ResponsiveActions measures button labels, chooses fitting columns/row height,
and preserves gaps and focus borders. Inputs stay outside the button grid;
related spectator controls and short tab content scroll.

Regression coverage includes real worker start and second-client reconnection,
completed-run recordings, run switching, champion locking, all mode transitions,
legacy Snake/Flappy artifacts, valid population replay with a damaged champion,
empty states, read-only queries during a WAL write lock, and action geometry,
keyboard focus and resizing at widths 80/100/120/160 and heights 24/50.

Baseline: `.venv/bin/python -m pytest -q`: 68 passed, 1 upstream warning, 53.99s.
Targeted spectator/interactions: 14 passed in 33.29s. Layout checks: 9 passed in
39.82s.

Final `.venv/bin/python -m pytest -q`: **88 passed, 1 warning in 106.44s**.
The warning remains Starlette's upstream httpx TestClient deprecation. The suite
includes 20 added regression cases. `.venv/bin/ruff check evoforge tests examples`,
`.venv/bin/ruff format --check evoforge tests examples` (61 files), and
`git diff --check` passed. No training algorithms, package version, or existing
experiment artifacts were changed.

Update an existing CachyOS checkout (fish-compatible):

```sh
cd ~/EvoForge
git switch feature/v1.0-universal-core
git pull --ff-only origin feature/v1.0-universal-core
.venv/bin/python -m pip install -e '.[tui]'
.venv/bin/evoforge workers list --root runs
```

Then reopen the existing experiment with `evoforge tui --output` pointing to its
actual directory, using the same venv. No checkpoint migration or deletion of
runs is needed. Native Konsole rendering still requires operator observation;
the geometry and keyboard checks above use Textual's headless test driver.
