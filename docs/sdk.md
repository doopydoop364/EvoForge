# Game SDK version 1

Install a trusted Python distribution declaring an `evoforge.games` entry point.
The entry point references a `GamePlugin` subclass, not an instance. Discovery
imports installed plugins only. There is no code upload or automatic installation.
Installing a plugin grants arbitrary Python execution under the operator account.
Review dependencies and code before explicitly installing a third-party package.

`GameInfo(id, name, version="1.0.0", score_name="score", sdk_version=1)` is immutable.
IDs must be unique lowercase slugs. Unsupported SDK versions and collisions are
reported as discovery errors. Constructor keyword arguments come from
`Config.game_config`. Metadata and spaces may be instance attributes.

Implement `reset(seed=None, options=None) -> (observation, info)` and
`step(action) -> (observation, reward, terminated, truncated, info)`.
Use a numeric Gymnasium Box and zero-based Discrete actions. The engine validates
observations and flattens multidimensional arrays in C order to float32; the
original shape remains declared on the plugin. No image/continuous encoder is
provided. Resets and action trajectories must be reproducible for the same seed.
The engine applies Config.max_steps as an additional episode time limit.

`fitness(info, episode_reward)` defaults to info['score'], falling back to episode
reward. Override to separate learning rewards and selection fitness. Return finite
numbers. `render()` returns terminal text. `spectator_frame()` returns bounded,
JSON-serializable data including a `text` field for generic terminal spectators.
`close()` releases resources and is invoked even when evaluation fails.

## Complete external example

From the repository root (commands also work in fish):

```sh
python -m pip install -e '.[dev,tui,api]'
python -m pip install -e examples/coin-game
evoforge games list
evoforge games inspect coin
evoforge games validate coin
```

See `examples/coin-game`: CoinGame has four flattened inputs and two actions,
deterministic seed handling, a configurable horizon, score fitness distinct from
+1/-1 learning rewards, terminal text and a registered package entry point.
Default policy widths `[64,64]` retain v0.9 state keys. Any positive list of MLP
widths is supported; crossover requires identical architecture metadata.
