# Development

Use Python >=3.10 on Linux. Install CPU torch followed by `-e '.[dev,tui,api]'`
and `-e examples/coin-game`. Keep changes on a feature branch and do not commit
runs, tensor archives, SQLite files, virtualenvs or caches.

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q -m integration
.venv/bin/python -m pytest -q -m textual
.venv/bin/ruff check evoforge tests examples
.venv/bin/ruff format --check evoforge tests examples
.venv/bin/python -m build
```

Tests use temporary roots. Integration tests spawn real owned workers and clean
up through the supervisor. Legacy compatibility tests generate runs using pinned
baseline commit `938b597`; fetch full Git history to run those tests. Textual tests
use Pilot clicks/forms and actual worker controls. They do not substitute for
real SSH/systemd/GPU acceptance. CI separates unit, integration, Textual, package
and quality checks and exercises Python 3.10–3.13.

Use GamePlugin for external environments, policy_for for dimensions, safe_load /
export_policy for artifacts, and Supervisor for all operator mutations. Do not
add UI dependencies to the trainer. Preserve legacy state keys and historical
CSV columns. Extend schema migrations explicitly rather than silently accepting
unknown versions. Metric/worker state mutations must be transactional and game
rewards must not be modified just to improve benchmark scores.

Report exact commands, outcomes, limitations and unresolved acceptance gates in
PROGRESS and RELEASE documentation. Keep version 1.0.0rc1 until final operator
acceptance; stable tags, merges and releases require explicit authorization.
