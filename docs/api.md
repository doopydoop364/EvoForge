# REST and WebSocket API v1

Install the API extra. Localhost binding is the default. Set a private token for
any remote binding (required by CLI and app factory); using a token locally is
recommended. Every /api/v1 HTTP request requires `Authorization: Bearer TOKEN`
when configured. WebSocket clients use the same header. Use SSH forwarding for
remote administration; direct network exposure requires a TLS reverse proxy.
OpenAPI schemas are at `/openapi.json`, interactive reference at `/docs`.

Fish example (store token in an owner-only config file or service EnvironmentFile):

```fish
set -gx EVOFORGE_API_TOKEN (python -c 'import secrets; print(secrets.token_urlsafe(32))')
evoforge api serve --root runs --host 127.0.0.1 --port 8765
```

Another terminal:

```sh
curl -H "Authorization: Bearer $EVOFORGE_API_TOKEN" http://127.0.0.1:8765/api/v1/games
```

Available routes:

- GET games, games/{id}, experiments, experiments/{id}, workers
- POST experiments with `{ "id": "demo", "config": { "game": "coin" } }`
- PUT experiments/{id} with a complete config; checkpointed runs only allow generation changes
- POST experiments/{id}/start, /pause, /resume, /stop (durable asynchronous requests)
- POST experiments/{id}/duplicate or /rename with `{ "destination": "new-name" }`
- DELETE experiments/{id} archives (never deletes historical data); POST /unarchive reverses it
- GET experiments/{id}/metrics, /agents, /champion, /export?format=csv
- GET compare?experiments=one,two&budget=100000
- WS events?since=SEQUENCE and experiments/{id}/spectator?since=SEQUENCE

All paths above are under `/api/v1`. 401 means invalid/missing authentication,
404 missing resource, 409 worker/lifecycle conflict, 422 invalid input. Controls
return the observed state; poll inspect or consume events until acknowledged.

Event batches carry `{events, cursor, gap}`; spectator batches use `frames`.
Reconnect with the last cursor. Empty batches are keepalives. Event history is
bounded to 512 entries; frame rings to 256. `gap=true` means retained history no
longer starts at the previous cursor. No subscriber owns a training queue.
Spectator WebSockets stream actual training frames, not synthetic policy replays.

The API accepts no Python uploads, shell commands, or filesystem paths. Run ids
are restricted slugs below a fixed server-owned root. The API is a privileged
single-operator service, not a multi-tenant sandbox. Installed game plugins run
with the operator account's privileges. Keep token, root and plugin installation
under the same trusted operator control. API docs reveal schemas but no run data.
