# Terminal operator guide

Launch `evoforge tui --output runs/demo`. Bare `evoforge` opens Textual when stdin
and stdout are terminals; headless invocation prints help. The optional classic
`dashboard` remains available, with supervisor controls and saved-policy replay.

The tabs are Overview, Experiments, Spectator, Analytics, Plugins, Workers, Logs,
and Settings. Tab/Shift+Tab move focus, Enter/Space activate buttons, arrows move
through tables and selection controls. Mouse clicks work with SSH terminals that
forward mouse events. Focused controls have a bright border.

- Ctrl+N creates the run named in the library's name input.
- Ctrl+S validates and saves settings; errors appear in the status line.
- Ctrl+R refreshes run state and the experiment library.
- Ctrl+Q exits and leaves workers running.
- Textual command palette (Ctrl+P) includes theme selection; themes persist using
  XDG_CONFIG_HOME/evoforge/preferences.json, defaulting to ~/.config.

The library's Create action opens Settings and focuses game selection. Enter
population, modes, episode counts, generation target and seed. The original
Hidden neurons field configures two equal layers; Hidden layer widths overrides
it with comma-separated widths. Plugin config is JSON, e.g. `{"horizon": 20}`.
Mutation and interaction budget fields are editable. Save before starting.
Checkpointed settings are protected; use Extend +100 or duplicate into a fresh
run. Rename/archive require a stopped worker. Duplicate copies configuration,
never checkpoints, metrics or worker identity.

Overview Start connects to the shared supervisor; a duplicate start reports a
conflict. Pause/Continue and Stop are requests, with acknowledged state visible
in Overview and Workers. Closing the app does not stop training. Reopen the same
run to control it from a second client.

Spectator Live Training consumes actual bounded worker frames. Champion Replay
loads and locks a saved champion until manually refreshed. Population Replay
loads independent saved policies. Grid/Focus, Next agent, speed, density and
selected-agent pause/restart affect replays. Live frames retain worker speed and
may skip sequences under load. Multiple viewers do not block training.

Analytics displays fitness histories and timings. Enter comma-separated run ids
for a comparison at the minimum available interaction budget. Results use the
last committed generation within that budget and label training/validation;
withheld test results are never fabricated. Export JSON/CSV writes export.json
or export.csv in the current run. Fitness spread is not genetic diversity.

Plugins lists installed games and validation results. Install reviewed packages
outside the app, then restart it to refresh entry-point discovery. Workers shows
identity-backed state, generation, PID and health. Logs reads worker output;
hardware load/RAM and available nvidia-smi data are informational.
