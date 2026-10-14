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
3. Persistent supervisor: pending.
4. Live telemetry: pending.
5. REST/WebSocket API: pending.
6. Analytics, Textual, documentation and release checks: pending.

No stable release/tag is authorized. Keep 1.0.0rc1 until operator acceptance.
