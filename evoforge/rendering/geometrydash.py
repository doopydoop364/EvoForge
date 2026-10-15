"""Bounded scenes captured from GeometryDash's actual simulator state.

Imported editor geometry is a 2D reference, not an assertion of 2D physics.
Unknown artwork is described as text; it is never replaced by invented sprites.
"""

import math
import time

from evoforge.geometrydash import SYMBOLS
from evoforge.gmd_import import BLOCKS, ORBS, PADS, PORTALS, SPIKES

from .gd_assets import ICON_SIZES, WORLD_FRAMES, WORLD_SIZES

COLORS = {
    "yellow": "#ffda5b",
    "pink": "#ff80d5",
    "red": "#ff5c5c",
    "blue": "#60baff",
    "green": "#68f098",
    "black": "#aaaaaa",
}
MAX_OBJECTS = 44


def _number(value, default=0, limit=10):
    try:
        number = float(value)
        return max(-limit, min(limit, number)) if math.isfinite(number) else default
    except (ValueError, TypeError):
        return default


def scene(env):
    unit = 28
    width, height = 640, 424
    # Follow tall arenas vertically instead of sending hundreds of tiny ground
    # tiles or shrinking the player below a readable size.
    floor = 344 + max(0, env.y - 8) * unit
    left = max(0, env.x - 4)
    right = left + width / unit
    nodes = []

    def sprite(identifier, asset, x, y, w=1, h=1, **extra):
        nodes.append(
            {
                "id": identifier,
                "kind": "sprite",
                "asset": asset,
                "x": x,
                "y": y,
                "width": w * unit,
                "height": h * unit,
                **extra,
            }
        )

    def label(identifier, text, x, y, **extra):
        nodes.append(
            {
                "id": identifier,
                "kind": "text",
                "text": text,
                "x": x,
                "y": y,
                "font_size": 13,
                "layer": 12,
                **extra,
            }
        )

    sprite(
        "background", "background", 0, 0, width / unit, height / unit, color="#234ea0", layer=-10
    )
    # Continuous native ground with true gaps removed. Restrict the viewport
    # and object count to keep normalized scenes below the telemetry budget.
    for column in range(int(left), math.ceil(right)):
        if env.hazards.get(column) != "_":
            sprite(
                f"ground-{column}",
                "ground",
                (column - left) * unit,
                floor,
                1,
                1.4,
                color="#486fd2",
                layer=-2,
            )
    sprite(
        "ceiling",
        "ground",
        0,
        floor - (env.size - 1) * unit,
        width / unit,
        0.25,
        color="#486fd2",
        layer=-2,
    )
    objects = []
    imported = env.imported_level
    if imported is not None:
        for index, obj in enumerate(imported.objects):
            x, y = obj["x"] / 30, (obj["y"] - 105) / 30
            if left - 2 <= x <= right + 2 and -2 <= floor / unit - y <= height / unit + 2:
                ident = obj["id"]
                asset = (
                    f"block-{ident}"
                    if ident in BLOCKS
                    else f"spike-{ident}"
                    if ident in SPIKES
                    else f"portal-{PORTALS[ident]}"
                    if ident in PORTALS
                    else f"orb-{ORBS[ident]}"
                    if ident in ORBS
                    else f"pad-{PADS[ident]}"
                    if ident in PADS
                    else None
                )
                if asset and asset not in WORLD_FRAMES:
                    asset = "orb" if ident in ORBS else "pad" if ident in PADS else None
                color = (
                    "#ac80ff"
                    if ident in PORTALS
                    else COLORS.get(ORBS.get(ident, PADS.get(ident)), "#ffffff")
                )
                objects.append((f"import-{index}", x, y, asset, str(ident), obj["raw"], color))
    else:
        for column, hazard in env.hazards.items():
            if hazard in ("^", "v") and left - 1 <= column <= right + 1:
                objects.append(
                    (
                        f"hazard-{column}",
                        column + 0.5,
                        env.size - 2 if hazard == "v" else 0,
                        "spike",
                        hazard,
                        {"5": "1"} if hazard == "v" else {},
                        "#ff5c5c",
                    )
                )
        for category, mapping in (
            ("portal", env.portals),
            ("orb", env.orbs),
            ("pad", env.pads),
            ("trigger", env.triggers),
        ):
            for column, entry in mapping.items():
                if not left - 1 <= column <= right + 1:
                    continue
                entries = entry if isinstance(entry, list) else [entry]
                for i, value in enumerate(entries):
                    kind = value.get("type", "") if isinstance(value, dict) else value
                    asset = f"{category}-{kind}"
                    if asset not in WORLD_FRAMES:
                        asset = category if category in ("orb", "pad") else None
                    y = 0 if category == "pad" else (env.size - 2) / 2
                    objects.append(
                        (
                            f"{category}-{column}-{i}",
                            column + 0.5,
                            y,
                            asset,
                            str(kind),
                            {},
                            "#ac80ff" if category == "portal" else COLORS.get(kind, "#ffffff"),
                        )
                    )
    # Closest to the observed player first when dense levels exceed the cap.
    objects.sort(key=lambda obj: abs(obj[1] - env.x))
    for identifier, x, y, asset, name, raw, color in objects[:MAX_OBJECTS]:
        native_w, native_h = WORLD_SIZES.get(asset, (30, 30))
        w, h = native_w / 30, native_h / 30
        factor = abs(_number(raw.get("32", 1), 1, 4)) or 1
        w, h = w * factor, h * factor
        px, py = (x - left) * unit - w * unit / 2, floor - y * unit - h * unit
        if imported:
            py += (h - 1) * unit / 2
        if asset:
            flip_x, flip_y = raw.get("4") == "1", raw.get("5") == "1"
            rotation = math.radians(_number(raw.get("6", 0), limit=360))
            sx, sy = -1 if flip_x else 1, -1 if flip_y else 1
            if imported:
                # Editor object coordinates are centers; protocol nodes rotate
                # around their local origin, so preserve the actual center.
                cx, cy = (x - left) * unit, floor - y * unit - unit / 2
                px = (
                    cx
                    - math.cos(rotation) * sx * w * unit / 2
                    + math.sin(rotation) * sy * h * unit / 2
                )
                py = (
                    cy
                    - math.sin(rotation) * sx * w * unit / 2
                    - math.cos(rotation) * sy * h * unit / 2
                )
            sprite(
                identifier,
                asset,
                px if imported else px + (w * unit if flip_x else 0),
                py if imported else py + (h * unit if flip_y else 0),
                w,
                h,
                color=color,
                rotation=rotation,
                scale_x=sx,
                scale_y=sy,
            )
        else:
            label(identifier, name[:40], px, py, color="#ffa65c")

    scale = 0.55 if env.mini else 1
    native_w, native_h = ICON_SIZES[env.mode]
    w, h = scale * native_w / 30, scale * native_h / 30
    px, py = (env.x - left) * unit, floor - env.y * unit - h * unit
    sprite(
        "player",
        env.mode,
        px + (w * unit if env.direction < 0 else 0),
        py + (h * unit if env.gravity == 1 else 0),
        w,
        h,
        scale_x=env.direction,
        scale_y=-1 if env.gravity == 1 else 1,
        color="#ff5050" if env.collision else "#50dcff",
        layer=8,
    )
    if env.collision:
        label("collision", "X", px, py - 22, color="#ff5050", font_size=20)
    if env.mirror:
        # Reflect the captured world around the viewport. HUD remains readable.
        for node in nodes:
            if not node.get("hud"):
                node["x"] = width - node["x"]
                node["scale_x"] = -node.get("scale_x", 1)
                node["rotation"] = -node.get("rotation", 0)
    state = (
        "COLLISION"
        if env.collision
        else "COMPLETE"
        if env.completed
        else "ENDED"
        if env.done
        else "RUNNING"
    )
    label(
        "mode",
        f"{SYMBOLS[env.mode]}  {env.mode.upper()}   {env.score}/{env.length} tiles   {state}",
        14,
        10,
        hud=True,
        font_size=18,
        color="#50dcff",
    )
    label(
        "state",
        f"Gravity {'up' if env.gravity == 1 else 'down'} | {env.speed} | "
        f"{'mini' if env.mini else 'normal size'} | {'reverse' if env.direction < 0 else 'forward'} | "
        f"{'held' if env.held else 'released'} | {'grounded' if env.grounded else 'airborne'}",
        14,
        38,
        hud=True,
    )
    flags = f"Mirror {'on' if env.mirror else 'off'} | Dual {'flag only' if env.dual else 'off'} | "
    flags += f"timewarp {env.timewarp:g} | dash {env.dash_frames}"
    label("flags", flags, 14, 58, hud=True)
    label(
        "events",
        " | ".join(f"{kind}: {name}" for kind, name in env.events)[:90],
        14,
        366,
        hud=True,
        color="#68f098",
    )
    note = (
        "Imported 2D reference; player/physics use a lossy column projection."
        if imported
        else "Captured simulator state; independent simplified GD-style physics."
    )
    label("source", note, 14, 388, hud=True, color="#ffda5b")
    omitted = max(0, len(objects) - MAX_OBJECTS)
    details = f"{omitted} visible objects omitted" if omitted else ""
    if imported:
        details += f" | {sum(imported.unsupported.values())} objects unsupported by physics"
    label("limitations", details.strip(" |"), 14, 406, hud=True, font_size=11)
    return {
        "protocol": 1,
        "width": width,
        "height": height,
        "background": "#102552",
        "timestamp": time.time(),
        "nodes": nodes,
    }
