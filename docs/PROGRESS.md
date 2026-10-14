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
6. Analytics, Textual, documentation and release checks: pending.

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

The full suite before the final two regression additions passed **66 tests** in
52.58s (`.venv/bin/python -m pytest -q`), with one upstream Starlette httpx
TestClient deprecation warning. Follow-up coverage preserves incomplete legacy
CSV rows/scientific notation and metadata for an uninstalled external plugin.

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
