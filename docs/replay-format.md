# Episode recording format 1

`evoforge.telemetry.recordings.Recording` is the formal validated schema. Each
recording is a JSON file under the run's `replays/` directory, named by a generated
32-hex id. HTTP APIs accept only these ids and supervisor-approved run ids.

Metadata: `format_version: 1`, `renderer_protocol: 1`, id, original run identity,
game id/version, agent id, seed (null only if unavailable), generation, episode
identity, source (training/validation/champion/population), creation time,
`complete`, `sampled`, `dropped`, and ordered frames. Rename preserves the original
recorded run identity as provenance while discovery follows the renamed run.

Frames store sequence, timestamp, environment step, actual score/reward,
terminated/truncated, validated scene or null, and text fallback. Sequence and
steps strictly increase; timestamps do not decrease. Missing simulation steps
remain missing. Live recordings are sampled and the UI labels them accordingly.
`complete` indicates that an episode-end frame was retained without known queue
or recording drops; it does not mean every simulation step was sampled.

Training persistence runs in a separate bounded queue/thread. Full queues drop
presentation frames without blocking simulation. Frames are retained even if a
browser is disconnected. Worker shutdown flushes partial episodes within a bounded
wait. There is no neural-network inference in recorded playback.

Limits: 128 queued payloads, 12 pending episodes, 2048 frames and a 4 MiB working
budget per episode; validated files are at most 8 MiB. Per-run retention defaults
to 100 episodes and 64 MiB, configured with `EVOFORGE_REPLAY_EPISODES` and
`EVOFORGE_REPLAY_BYTES`. Oldest recordings are deleted first under a file lock;
checkpoints and metrics are never deleted by replay retention. Storage is per run,
so account for the number of experiments when sizing the disk.

Champion/population generation loads safe existing model artifacts on the server,
uses the requested seed, and generates one episode per agent (up to nine), bounded
by the frame, byte and execution-time limits. Its presentation timestamps are
explicit 20 Hz playback timing, not claimed historical training timestamps.
Truncated recordings are labeled partial. Only one generation request runs at a
time per API process. The browser reads frames in pages (maximum 512 per request),
then supports play/pause/restart, speed and scrubbing locally.

Unknown format/renderer versions and malformed/order-invalid recordings are rejected;
they are not silently migrated. Install the matching plugin version to recover
its exact assets. Existing checkpoints and text telemetry remain compatible;
no historical scenes are fabricated for old runs. Video export is not included.
