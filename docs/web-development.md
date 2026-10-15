# Web development

The React/TypeScript application in `web/` uses Vite, Tailwind, TanStack Query,
Recharts and PixiJS. It consumes the existing supervisor API at `/api/v1`.
There are no sample experiments, worker states or historical metrics in production UI.
The backend stable version is unchanged; the web client is independently versioned 0.1.0.

## Install and start

Use Python 3.10+ and Node 22.12+ (Node 24 also works). From the repository:

```sh
python -m venv .venv
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -e '.[dev,tui,api]' -e ./examples/coin-game
npm --prefix web ci
.venv/bin/evoforge api serve --root ./runs --host 127.0.0.1 --port 8765
```

In another terminal:

```sh
npm --prefix web run dev
```

Open http://127.0.0.1:5173. Vite forwards HTTP and WebSocket `/api` traffic to
127.0.0.1:8765 without changing its Host header. Set `EVOFORGE_BACKEND` for a
different development backend. Do not expose the Vite server remotely.

If the backend has `EVOFORGE_API_TOKEN`, enter it on the sign-in screen. The browser
exchanges it for an HttpOnly session cookie and clears the form. Only theme is
stored in localStorage. Backend restart or eight hours expires a session.

## Architecture

- `web/src/api.ts`: typed, same-origin HTTP client, errors and exports.
- `App.tsx`, `ExperimentForm.tsx`: navigation, dashboard, supervisor lifecycle,
  confirmation dialogs, configuration, plugin/worker/log/settings screens.
- `Spectator.tsx`, `stream.ts`: live frame cursor/reconnection and recorded,
  champion and population playback; per-agent pause, speed, restart and scrubbing.
- `SceneView.tsx`: one generic Pixi renderer for every conforming plugin.
- `Analytics.tsx`: measured fitness, validation, champion, throughput, duration,
  population distributions, PPO and experiment comparisons.
- `evoforge/rendering`: bounded scene schema, manifest and asset validation.
- `evoforge/telemetry/recordings.py`: asynchronous bounded episode persistence and
  isolated server-side policy replay. It never drives the training worker.
- `evoforge/api/web.py`: services using existing supervisor/path validation.

The original Textual UI and CLI remain independent clients. Duplicate creates a
fresh experiment with identical configuration, preserving all source artifacts;
rename and archive retain the existing run's artifacts. Extend changes only the
generation target of a stopped run with a checkpoint.

## Validation

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check evoforge tests examples
.venv/bin/ruff format --check evoforge tests examples
npm --prefix web run typecheck
npm --prefix web run lint
npm --prefix web test
npm --prefix web run build
npm --prefix web run test:e2e
.venv/bin/python -m build
```

Playwright starts a real authenticated FastAPI server on port 8766 with a temporary
storage directory and stops its workers on shutdown. It uses system Chromium when
available, otherwise the Playwright-installed browser. Override `EVOFORGE_CHROMIUM`
with a browser executable, or run `cd web; npx playwright install --with-deps chromium`.
Browser traces and screenshots are written under ignored `web/test-results/`.
Tests do not touch `./runs`. Do not weaken assertions or remove required checks.

## Interface behavior

Empty, unavailable and failed data are labeled. Historical resource utilization
is not collected, so the dashboard shows a current host load/memory snapshot; CPU
load is not presented as a utilization percentage. CUDA availability is reported
without assuming compatible kernels. PPO charts appear only for measured PPO
refinements. Comparisons retain per-run game/version, seed and budget metadata;
matched-budget comparisons require identical environment configuration and select
actual committed measurements, without interpolation.

Use keyboard Tab/Shift+Tab to navigate. The theme persists locally; reduced-motion
preferences disable animation/interpolation. Narrow layouts move navigation behind
a menu and keep experiment tables horizontally scrollable.
