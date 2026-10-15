# Web troubleshooting

- **404 at `/`:** run `npm --prefix web ci` and `npm --prefix web run build`, then
  restart the API. When installed from a wheel, set `EVOFORGE_WEB_DIR` to the build.
- **401 / sign-in required:** enter the configured operator token. Sessions expire
  in eight hours or on API restart. API calls need a Bearer header outside a browser.
- **400 Invalid host:** add the exact DNS/IP name to `EVOFORGE_ALLOWED_HOSTS` and
  restart. Keep the proxy's original Host. Do not use a wildcard.
- **403 / WebSocket 4403:** browser Origin and Host must match. Use the same-origin
  proxy configuration. Vite must proxy `/api`, including WebSockets.
- **Reconnecting:** confirm the backend is running and the reverse proxy forwards
  Upgrade headers. The client resumes from the last sequence and reports ring gaps.
- **No live frames:** start a worker and choose Live Training. Only the first three
  evaluated agents are sampled by the existing telemetry publisher. Completed or
  stopped runs show saved ring frames; historical gaps are never synthesized.
- **No champion/population replay:** complete at least one generation so champion
  and spectator artifacts exist. If a replay exceeds limits it is labeled partial.
- **No recordings:** pre-web runs have no scene recordings. New workers record
  sampled episodes; inspect disk permissions/retention settings and worker logs.
- **Rendering fallback:** inspect the displayed error, manifest paths, scene schema
  and installed plugin version. WebGL-disabled clients can read text fallback.
  Missing images show placeholders. SVG scripts/HTML/external references are invalid.
- **Blocked rename/archive/extend:** stop the active worker first. Duplicate creates
  a new configuration; it does not clone another worker's checkpoint identity.
- **Different-game comparison rejected:** raw reward scales are not interchangeable.
  Matched-budget comparison requires the same game version/configuration and measured
  environment-step history. No measurement below the common budget means unavailable.
- **No PPO/resource series:** old metrics and non-PPO runs do not provide those
  values. Host resource snapshots are not fabricated historical time series.
- **Playwright browser missing:** install Chromium or use Playwright's installer;
  set `EVOFORGE_CHROMIUM` if needed. Port 8766 must be free for the disposable server.
