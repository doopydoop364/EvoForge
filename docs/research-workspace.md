# EvoForge research workspace

The research workspace adapts the supplied Evolution Engine laboratory's visual direction and research workflows to EvoForge's existing React application and training engine. It retains evolution, PPO, hybrid training, installed game plugins, supervisor controls, authentication, and the game spectator. The supplied Python engine and its bundled environment are not dependencies and were not executed.

## Open the workspace

Install EvoForge with its API dependencies and PyTorch 2.10 or newer, build `web/`, and run the existing API server. For example, from the checkout:

```sh
python -m pip install '.[api]'
npm --prefix web ci
npm --prefix web run build
python -m evoforge.cli api serve --root runs --port 8765
```

Open `http://127.0.0.1:8765`. A remote binding still requires the existing operator token and allowed hosts/origins. The paper theme is the initial default; existing saved theme preferences are respected.

## Pages and workflows

| Page | Implemented behavior |
|---|---|
| Dashboard / Experiments | Existing live metrics and lifecycle controls, plus search by name, game, algorithm, tags and note preview; status filters; research notebooks and independent-seed batch creation. |
| Family Trees | Recorded parent edges across three generations, selectable agents, parameter fingerprints, historical score boundaries, pagination, and saved bookmarks. |
| Genetic Comparison | Full per-layer difference statistics, sampled weight heatmaps, retained-generation selection, and cancellable behavior probes on actual environment observations. |
| Evolution Replay | Exact-generation measurements and population scores, playback/scrubbing, a bounded history chart, and the recorded champion selection timeline. This is a history browser; game footage stays in Spectator. |
| Compare Runs | Existing environment-compatible, common-budget comparisons and measured charts, plus seed replication batches. Validation scores are explicitly separate from withheld-test claims. |
| Tournament Lab | Immutable champion snapshots, shared seed scenarios for any compatible game, or simultaneous head-to-head RPS matches. Per-trial outcomes, paired results, measured interaction counts, and JSON exports are saved. |
| Research Bookmarks | Experiment notes, tags, saved family/history/agent views, and reopening the recorded selection. |
| Storage Manager | Per-run usage, free disk, research/replay usage, a configurable historical-weight budget, and explicitly confirmed replay removal. |
| Backups | Create, verify, download, import, restore into a new experiment, and explicitly remove portable per-experiment archives. |
| System Resources | CPU, memory, active workers, and durable research jobs with progress, cancellation, errors, and exports. |
| Benchmarks | Warmed CPU inference timing for a saved champion, with batch size, warmup, parameter count, runtime version, median and 95th-percentile timings. |
| Spectator / Games / Workers / Logs / Settings | Existing EvoForge functionality, including the Geometry Dash spectator work on which this branch is based. |

## Data model and recovery

Training checkpoints remain authoritative. Each experiment has a derived `research.sqlite` containing:

- Agent occurrence identities `generation:slot`, recorded parent identities and operations, and SHA-256 fingerprints of architecture, named parameter layout, and float32 bytes.
- Committed evaluation history, retained population weights, notes, tags and bookmarks.
- The scientific manifest: source digest, package/runtime versions, environment settings and plugin version, external Geometry Dash level/importer digests where applicable, and the validation seed protocol.

Training captures generation zero and each committed next population. Scores describe the population **before** reproduction/PPO refinement. A next-population node has no recorded score until it is evaluated. The existing champion remains the best candidate selected on the reused validation seeds; this update does not change the training algorithm or claim a final withheld-test evaluation.

When a checkpoint is recovered, indexing deletes research observations beyond its commit and removes scores not yet established by that commit. Existing notes and bookmarks survive. Old checkpoint indexing runs only while the worker is stopped and preserves unknown ancestry/weights as unknown. It cannot reconstruct unsaved history. New PPO runs explicitly record their parent links.

New manifests record the environment content identity and reject a changed identity on resume. Legacy manifests identify their incomplete provenance. Content identity is checked at job submission and resume; external files should remain stable during a running experiment. Cross-platform or cross-version bitwise equivalence is not promised.

## Storage and operational boundaries

Historical parameter retention defaults to **64 MiB of active parameter blobs per experiment**, configurable from 0–1024 MiB. Old weights are evicted first; lineage metadata, annotations, metrics and authoritative checkpoints remain. SQLite may keep reusable free pages until the explicit retention operation vacuums the database. Setting zero disables retained weights for future commits as well.

History charts return at most 300 uniformly sampled committed rows by default, including endpoints. Selecting a generation retrieves its exact measurement. The chart does not pretend to preserve every between-sample extremum. Family queries return at most 500 nodes, with pagination. Heatmaps display at most 96 cells per layer; statistics use the complete retained layer.

Research jobs run in detached processes, separately from training RNG and the web server, with one research job at a time and one CPU thread. Analysis is cooperatively bounded to 180 seconds and 250,000 steps/checks. Requests exceeding the estimated step budget are rejected. Cancellation is checked between steps, analysis iterations and backup files. Installed game callbacks must return for cooperative cancellation to take effect. An exited process without a committed result is shown as interrupted, never completed. Up to 100 jobs are retained; finished jobs can be exported and removed.

Inputs are copied at submission and hashed. Results persist under `.research-jobs/` across web-server restarts. Removing a job removes its stored input snapshots and result. A resumed worker is independent of the browser session.

## Backups and imports

Backups are per experiment and require a stopped worker. They contain the run configuration, primary/backup checkpoints, champion/spectator snapshots, metrics, a consistent SQLite research snapshot, and captured replay files. Worker PIDs, locks, live telemetry, process logs, installed plugins, external game assets, and workspace-wide research-job directories are excluded. Export analysis jobs separately when preserving tournament or benchmark results.

The archive contains a versioned manifest with every member's size and SHA-256 digest. Validation rejects unsupported paths, links, duplicate entries, encrypted members, oversized data, inconsistent manifests, damaged databases, non-finite/wrong-shaped parameters, malformed continuation RNG state, and invalid replay records. Tensor loading uses restricted PyTorch loading with a runtime minimum version. Backup validation enforces a 512 MiB expanded tensor-archive limit; normal training checkpoint loading keeps its existing size behavior. No unsafe pickle fallback or uploaded-code installation is available.

Archives are limited to 512 MiB expanded and 511 data files. Imports stream to a temporary file, validate before publication, and use the existing authentication/origin checks. Restore requires a new run name, validates the installed environment, preserves scientific data, and starts no worker. Keep the source archive if an external plugin is currently unavailable.

## RPS benchmark

The included RPS environment is a new EvoForge SDK implementation with nine observations: the opponent's last three moves, one-hot encoded, newest first. Actions are rock=0, paper=1, scissors=2. Configuration accepts `opponent` (`cycle`, `random`, `repeat`, `counter`) and `horizon` (default 23). Moves are selected using past information only.

The optional head-to-head tournament compares frozen RPS champions directly. Each seed generates the same three-move initial history for both players. Both decisions are made before either current move is revealed. Results report wins, losses, draws and net wins per throw. This is an evaluation tool, not a change to EvoForge's training into a coevolution engine.

## Validation

The added backend tests cover lineage and recovery, retention, history bounds, parameter comparisons, archive integrity and traversal rejection, authenticated APIs, environment identity checks, persistent/cancelled jobs, deterministic tournaments, RPS simultaneity and completion-status races. Browser acceptance covers actual training, persisted notes, family bookmarks, weights and behavioral probes, history playback, tournament and benchmark results, ZIP download/import/restore, retention and the mobile notebook. Existing terminal and spectator suites remain part of verification.
