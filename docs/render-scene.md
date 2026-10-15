# Renderer protocol 1

The formal schema is `evoforge.rendering.schema.Scene`. Simulation has no browser
or Pixi dependency. Plugins optionally implement `render_scene() -> dict | None`
and `get_asset_manifest()` and may retain `render()`/`render_terminal()` for Textual.
`render_scene()` is invoked only when gameplay is sampled or a separate replay is
requested. It must not mutate simulation state. Invalid scenes produce an explicit
`render_error` plus the existing text fallback; training continues.

The spectator opens in **Text** mode for both sampled frames and replays. Text
mode never requests an asset manifest or starts a graphics renderer. Users can
select **Display → Game graphics** to view the game's optional presentation.
A text-only game (including the Geometry Dash-style simulator) does not need
assets; selecting graphics for a recording without a scene keeps its captured
text visible with an explanation rather than reporting an asset failure.

Plugins can provide their own graphical spectator through `render_scene()` and
`get_asset_manifest()`: sprites, tilemaps, custom shapes, animations, camera
position/zoom and a screen-space HUD are supported. Asset-free scenes can use
rectangles and text with the default empty manifest. The renderer remains
independent of training; a plugin must retain `render()` for Text mode. See the
installed Coin example for an entire graphical plugin. Custom browser code is
not required; the declarative renderer protocol is the extension interface.

A scene declares `protocol: 1`, integer width/height (16–4096), `coordinates`
(`y-down` default or `y-up`), six-digit hex background, timestamp, optional camera
{x,y,zoom}, nodes and animations. Missing camera centers the full canvas. Units
are logical pixels. Zoom is 0.1–10; the viewer adds its own zoom and aspect-fit
resize. Rotation is in radians around the node's top-left origin.

Each node has a unique logical id and kind `sprite`, `rect`, `text` or `tilemap`.
It supports x/y, width/height, scale_x/scale_y, layer (-100–100), visibility,
opacity (0–1), asset id, animation id, text (up to 1024 characters), color,
font_size and `hud`. HUD coordinates are screen-relative and independent of the
world camera. World elements sort by layer; the HUD renders above the world.

Tilemaps declare columns, a palette of logical asset ids and row-major integer
tile indices (-1 is empty). Node width/height are tile dimensions. Animations
map identifiers to {frames: [asset ids], fps: 1..60}; sprites choose a frame from
elapsed presentation time. Reduced motion disables animation and positional
interpolation. Missing images render visible geometric placeholders.

Limits: at most 4096 nodes, 64 animations, 120 frames per animation, 256 palette
entries, 16384 total rendered elements, finite bounded numeric coordinates,
256 KiB raw JSON and 48 KiB normalized scene JSON. The tighter normalized limit
preserves room for the existing text and metadata inside 64 KiB telemetry frames.
Unsupported versions, duplicate ids, unknown animations, invalid tile indices,
NaN/infinities and unknown schema fields are rejected. Scenes contain no HTML,
JavaScript, arbitrary URLs, shaders, fonts or executable expressions.

Example (omitted fields receive documented schema defaults):

```python
def render_scene(self):
    return {"protocol": 1, "width": 480, "height": 320,
            "nodes": [
                {"id": "player", "kind": "sprite", "asset": "player",
                 "x": self.x, "y": self.y, "width": 48, "height": 48},
                {"id": "score", "kind": "text", "hud": True,
                 "x": 16, "y": 16, "text": str(self.score)}]}
```

The external Coin package is a complete installed-entry-point example. Snake and
Flappy use presentation adapters without changing observations, rewards or physics.
Future incompatible scene protocols require an explicit new version; v1 clients
must reject unknown versions rather than interpret them silently.
