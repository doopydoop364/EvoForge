# Spectator protocol

Workers publish actual evaluation environment frames, sampled at 25 Hz plus
terminal frames for up to three evaluated agents. They never delay simulation to
match display speed. Payloads include experiment/worker/game identity, generation,
agent, globally unique episode id, episode index, timestamp, reward, score,
termination/truncation, phase, game data and monotonic sequence. Generic terminal
clients render `data.text`; additional JSON game data is available to consumers.

Each run has a separate SQLite WAL ring with 256 frames, maximum 64 KiB per frame.
Writer lock contention drops a frame immediately; no spectator can block training
on a frame write. Multiple readers independently track their last seq. Reconnect
with the previous cursor. Gaps are expected when data is overwritten; clients
should show a gap and display the most recent frame. Invalid/non-JSON game data is
a plugin error, not silently substituted fake frames.

Textual's Live Training mode reads these frames. Champion Replay and Population
Replay simulate saved policies independently. Champions stay locked until manually
loaded again; generation updates never replace a replay. Replay speed/density and
focus controls do not alter training. A replay of an archived generation snapshot
is labeled replay, never live gameplay.
