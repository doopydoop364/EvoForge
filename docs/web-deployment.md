# Web deployment

No deployment is performed automatically. Production runs and release tags are not
changed by installing the browser application.

## Build and serve on one origin

```sh
npm --prefix web ci
npm --prefix web run build
.venv/bin/evoforge api serve --root /absolute/path/to/runs --host 127.0.0.1 --port 8765
```

FastAPI serves `web/dist` when present at startup. A wheel installed separately
from the checkout can serve a separately built frontend by setting
`EVOFORGE_WEB_DIR=/absolute/path/to/web/dist`. The Python wheel includes game assets;
it does not bundle the frontend build. Build the frontend from the matching commit.
The root directory is selected only by the operator's CLI/environment, never HTTP.
Use one API server process per deployment. Workers remain independent processes.

The authenticated health endpoint is `GET /api/v1/health`. For token-protected
installations, supply `Authorization: Bearer ...`. Logs go to the server journal
and each run's existing `training.log`; the UI exposes only its latest 64 KiB.

## SSH forwarding (recommended for personal LAN use)

Keep the API on localhost on the training machine. From another machine:

```sh
ssh -N -L 8765:127.0.0.1:8765 your-user@training-machine
```

Open http://127.0.0.1:8765 on the client. SSH provides transport encryption and
remote authentication. The application remains on its default localhost binding.
Do not create a public tunnel or disable certificate verification.

## HTTPS reverse proxy

Use the example `contrib/evoforge-web.nginx.conf`, replace its hostname and TLS
certificate paths, and keep the upstream on 127.0.0.1. Permit only your intended
LAN clients in the firewall. Configure these environment variables for the API:

```text
EVOFORGE_API_TOKEN=<operator-generated-high-entropy-token>
EVOFORGE_ALLOWED_HOSTS=forge.example.internal
EVOFORGE_WEB_DIR=/absolute/path/to/EvoForge/web/dist
EVOFORGE_REPLAY_BYTES=67108864
EVOFORGE_REPLAY_EPISODES=100
```

These are examples, not commands containing a real token. Generate a token with
`python -c 'import secrets; print(secrets.token_urlsafe(32))'` and keep the environment
file readable only by your service account. Never commit it. WebSocket Upgrade,
Host and forwarded HTTPS scheme must be passed correctly. Uvicorn trusts forwarded
headers only from its configured trusted proxy addresses (loopback by default).

For a deliberate direct LAN bind, `--host 0.0.0.0` refuses startup without
`EVOFORGE_API_TOKEN`; also configure the exact permitted DNS/IP Host in
`EVOFORGE_ALLOWED_HOSTS`. Use a TLS reverse proxy or SSH rather than transmitting
credentials over plain LAN HTTP. CORS is closed; no wildcard public access is needed.

## systemd user service

See `contrib/evoforge-web.service`. Adapt its checkout and data paths, create
`~/.config/evoforge/api.env` with mode 0600, and install the unit under your user
systemd directory. Enable it only when you choose to deploy:

```sh
systemctl --user daemon-reload
systemctl --user enable --now evoforge-web.service
journalctl --user -u evoforge-web.service -f
```

`KillMode=process` preserves the established detached-worker lifecycle. Stop workers
through the application before maintenance when you want training to end. Back up
the entire storage directory, including SQLite metadata and checkpoints.

## CachyOS and fish

```fish
sudo pacman -S --needed python nodejs npm chromium
python -m venv .venv
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -e '.[dev,tui,api]' -e ./examples/coin-game
npm --prefix web ci
npm --prefix web run build
set -x EVOFORGE_WEB_DIR $PWD/web/dist
.venv/bin/evoforge api serve --root $PWD/runs --host 127.0.0.1
```

No shell activation is required. For development, use `set -x EVOFORGE_BACKEND
http://127.0.0.1:8765` followed by `npm --prefix web run dev` in a second terminal.
Arch-family Python updates can require recreating the virtual environment. Use CPU
Torch unless `evoforge doctor` verifies your GPU kernels; older NVIDIA GPUs may not
be supported by current CUDA wheels.

## Operator acceptance

After choosing to deploy, verify the service starts after login/reboot as intended,
SSH/HTTPS access from your actual LAN client, token rejection, WebSocket reconnect,
filesystem permissions, disk limits, backups and your target GPU/browser. These
machine-specific deployment checks cannot be established by repository CI.
