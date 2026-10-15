# Geometry Dash web spectator

Open an experiment's **Spectator** and select **Display → Game graphics**.
Text remains the default for every game and works without graphical dependencies.
Snake, Flappy and plugin rendering are unchanged.

The Geometry Dash adapter captures the simulator's actual state into the shared
renderer protocol. Live telemetry, saved training episodes, champion replays and
population replays all use this same path. Rendering never steps the environment
or consumes its random generator. Position changes snap to the captured sample;
the browser does not invent intermediate physics. Sampling, buffer gaps, stale
frames and partial recordings retain the existing spectator labels.

## Original game artwork

No generated artwork or substitute sprites are included. EvoForge reads the
original PNG/plist files from a locally installed copy of Geometry Dash. Install
the optional decoder in the server's Python environment:

```sh
python -m pip install -e '.[api,gd-assets]'
```

Steam installations under `~/Steam`, `~/.steam/steam`, `~/.local/share/Steam`,
Flatpak Steam, and libraries listed in their `libraryfolders.vdf` are detected.
For other installations, set this before starting the API server:

```sh
export EVOFORGE_GD_RESOURCES='/path/to/steamapps/common/Geometry Dash/Resources'
```

The server reads only allowlisted sprite frames from `GJ_GameSheet.plist`,
`GJ_GameSheet02.plist`, their PNG sheets, the eight `icons/*_01.plist`/PNG files,
and original background/ground PNGs. Cocos format 3 rotation and trim offsets
are decoded into memory; no game files are changed or copied into the repository.
Sprites use authenticated, content-addressed asset routes. Asset IDs are never
interpreted as filesystem paths. Restart the server after changing the source
assets; decoded sprites are cached for that process. An explicit missing Resources
folder does not silently fall back to another installation.

If the installation, Pillow, an atlas, or a required sprite is unavailable,
the spectator shows captured text with an explanation. It does not draw substitute
rectangles or icons. Remote deployments must configure assets on the server.

## State, symbols and objects

The captured HUD shows mode, score/length, collision/completion, gravity, speed,
mini size, direction, held input, grounded state, mirror, timewarp, dash frames,
the dual flag and recent object events. The native base icon changes with mode,
size, direction and gravity. Collision tints it red and adds `X`. Mirror reflects
the world while keeping the HUD readable. Color tint now applies to sprite nodes;
other games' white default tint preserves their source pixels.

Native portal, orb and pad frames identify supported objects, with diagnostic
text for modifiers lacking mapped artwork and for physical triggers. Gaps remove
ground tiles. Unknown imported objects have numeric ID labels rather than fake
artwork. The expandable legend explains the simulator's stable ASCII symbols.

Old text-only GD frames can be displayed using their captured cells and symbols.
Missing portal types, gravity, mini, mirror and other unrecorded state are not
reconstructed. Unrecognized or malformed boards stay as text.

## Imported levels and limits

Set `EVOFORGE_GMD_LEVEL` as before to import `.gmd`/`.gmd2` levels. The environment
retains the original objects so the spectator can show distinct 2D heights,
overlapping objects, rotation, flips and uniform scale. Nonfinite coordinates are
ignored by the importer. This is labeled **Imported 2D reference**: the player's
position comes from the simulated state, whose physics still use the existing
lossy column projection. Drawing a block at its original height does not give
that block authoritative 2D collision physics.

These are independent simplified GD-style physics, not the original game engine.
There is one simulated player; dual is a flag only. Native base icon sprites are
static, and robot/spider use their native body sprite without skeletal animation.
Original player customization, multipart/glow layers, level color channels,
decorative object mapping, slopes, custom triggers and camera effects are not
reproduced. The spectator tint palette describes simulator categories rather
than reconstructing the original level's colors. Portal/orb effects retain the
simulator's simplified activation rules.

Only the viewport's objects are sent, capped at 44 nearest objects plus terrain,
player and HUD to fit the shared 48 KiB normalized scene budget. Omitted visible
objects and unsupported physics objects are counted; this does not remove them
from simulation/import data. Very large scenes can still use the generic text
fallback if a scene fails validation. No game physics or observation/action
dimensions are changed by the presentation adapter.

Saved scene recordings preserve what was captured. Champion/population replay
generation uses the server's current `EVOFORGE_GMD_LEVEL`, as in the existing
simulator: checkpoints do not embed imported level files, so retain and configure
the same level when generating a new replay. Sampled recordings cannot recover
frames that were not captured, and existing replay storage/time limits apply.

## Validation

`tests/test_geometrydash_rendering.py` covers capture independence, all eight
modes, modifiers, object bounds, dense/imported 2D scenes, original atlas decoding,
optional/authenticated assets, WebSocket capture, saved scenes, and actual
champion/population generation. Frontend tests cover legacy boards and missing
original artwork. Browser acceptance tests exercise a real worker, saved episodes,
replay seeking and model replays; original art assertions run when a local
installation is available. No substitute game artwork is used in those browsers.
