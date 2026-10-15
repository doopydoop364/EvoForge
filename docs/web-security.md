# Browser security model

The web client extends the existing operator API token model. Localhost is the
default bind. Remote binding requires `EVOFORGE_API_TOKEN`. Exact Host validation
and same-origin HTTP/WebSocket Origin checks protect local deployments against
DNS rebinding and cross-site browser requests. Set exact extra hosts with
`EVOFORGE_ALLOWED_HOSTS`; there is no public wildcard by default. CORS remains
closed. `EVOFORGE_ALLOWED_ORIGINS` may list exact origins for a controlled proxy
setup, but does not itself enable cross-origin browser CORS access.

HTTP routes accept the existing Bearer header. `POST /api/v1/session` exchanges
valid authentication for an HMAC-authenticated, eight-hour HttpOnly/SameSite=Strict
cookie, Secure when served via HTTPS. The signing key is random per server process;
restart invalidates sessions. Browser WebSockets use that cookie because browser
WebSocket APIs cannot set arbitrary Authorization headers. CLI WebSockets retain
Bearer-header support. Tokens are never put in localStorage or WebSocket URLs.
Use SSH forwarding or HTTPS for remote access; never send a real token over plain
untrusted HTTP. This is an operator control plane, not a multi-tenant RBAC system.

All experiment mutations use the existing supervisor, file locks and state
transitions. Browser confirmation is required for lifecycle, archive, rename and
extension actions. No endpoint accepts shell commands, arbitrary filesystem paths,
Python uploads or plugin installation. Supervisor ids constrain run access.
Plugin Python code remains explicitly installed and fully trusted by the operator.

Requests are capped at 64 KiB even when chunked, JSON nesting at 12 levels and
complexity at 4096 items. Hidden-layer widths are bounded by the API. Scenes,
assets, replay pages/files, telemetry rings and recording queues are independently
bounded. Asset content is authenticated, allowlisted and served with `nosniff` and
sandbox CSP; executable SVG/HTML/JS content is rejected.

Policy artifacts are loaded through the existing safe tensor loader, on the server.
Recording JSON stores no executable tensors. Missing images degrade to placeholders
or text. Invalid scenes do not fail training. Replay generation is serialized and
bounded independently of simulation. Monitoring does not run shell commands or
assume a CUDA-capable machine.
