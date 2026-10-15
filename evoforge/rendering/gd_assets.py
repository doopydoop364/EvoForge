"""Read original sprites from the operator's Geometry Dash installation.

No game artwork is bundled, downloaded, or replaced with substitute artwork.
Only the fixed frame allowlist below is exposed to the browser. The in-memory
PNG crops retain the original pixels, including rotated/trimmed atlas frames.
"""

import hashlib
import io
import os
import plistlib
import re
from functools import lru_cache
from pathlib import Path

ICON_FRAMES = {
    "cube": ("player", "player_01_001.png"),
    "ship": ("ship", "ship_01_001.png"),
    "ball": ("player_ball", "player_ball_01_001.png"),
    "ufo": ("bird", "bird_01_001.png"),
    "wave": ("dart", "dart_01_001.png"),
    "robot": ("robot", "robot_01_01_001.png"),
    "spider": ("spider", "spider_01_01_001.png"),
    "swing": ("swing", "swing_01_001.png"),
}
PORTAL_FRAMES = dict(
    zip(
        (
            "gravity_normal",
            "gravity_reverse",
            "cube",
            "ship",
            "mirror_on",
            "mirror_off",
            "ball",
            "normal_size",
            "mini",
            "ufo",
            "dual_on",
            "dual_off",
            "wave",
            "robot",
            "teleport",
            "spider",
            "swing",
        ),
        (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18),
    )
)
WORLD_FRAMES = {
    "spike": "spike_01_001.png",
    "spike-8": "spike_01_001.png",
    "spike-39": "spike_02_001.png",
    "spike-103": "spike_03_001.png",
    "block": "square_01_001.png",
    **{f"block-{i}": f"square_{i:02d}_001.png" for i in range(1, 8)},
    "orb": "ring_01_001.png",
    "pad": "bump_01_001.png",
    "orb-pink": "ring_02_001.png",
    "orb-red": "ring_03_001.png",
    "pad-pink": "bump_02_001.png",
    "pad-red": "bump_03_001.png",
    "orb-dash_green": "dashRing_01_001.png",
    "orb-dash_pink": "dashRing_02_001.png",
    "orb-spider": "spiderRing_001.png",
    "pad-spider": "spiderBump_001.png",
    "orb-custom": "ring_custom_01_001.png",
    "orb-blue": "gravring_01_001.png",
    "orb-green": "gravJumpRing_01_001.png",
    "orb-black": "dropRing_01_001.png",
    "orb-teleport": "teleportRing_001.png",
    "pad-blue": "gravbump_01_001.png",
    **{
        f"portal-speed_{k}": f"boost_{i:02d}_001.png"
        for i, k in enumerate(("slow", "normal", "fast", "faster", "very_fast"), 1)
    },
    **{f"portal-{k}": f"portal_{v:02d}_front_001.png" for k, v in PORTAL_FRAMES.items()},
}

# Logical dimensions of the original 1x frames. Keeping these separate from the
# optional decoder lets telemetry preserve aspect ratios even without artwork.
ICON_SIZES = dict(
    zip(
        ICON_FRAMES,
        ((30, 30), (37, 23), (35, 35), (37, 16), (26, 21), (28, 20), (30, 20), (36, 30)),
    )
)
WORLD_SIZES = {
    "pad": (25, 4),
    "pad-pink": (29, 7),
    "pad-red": (25, 5),
    "pad-blue": (25, 6),
    "pad-spider": (29, 15),
    "orb-pink": (32, 32),
    "orb-black": (33, 33),
    "orb-spider": (39, 39),
    "orb-dash_green": (39, 35),
    "orb-dash_pink": (39, 35),
    "orb-custom": (29, 29),
    "orb-teleport": (37, 37),
    **{f"portal-{k}": (45, 86) for k in PORTAL_FRAMES},
    **{f"portal-{k}": (35, 77) for k in ("gravity_normal", "gravity_reverse")},
    **{f"portal-{k}": (59, 91) for k in ("mirror_on", "mirror_off")},
    **{f"portal-{k}": (44, 90) for k in ("normal_size", "mini")},
    **{f"portal-{k}": (43, 90) for k in ("dual_on", "dual_off")},
    "portal-teleport": (55, 90),
    "portal-spider": (45, 85),
    **dict(
        zip(
            (f"portal-speed_{k}" for k in ("slow", "normal", "fast", "faster", "very_fast")),
            ((35, 44), (33, 57), (51, 57), (65, 57), (69, 57)),
        )
    ),
}


def resources_path():
    configured = os.environ.get("EVOFORGE_GD_RESOURCES")
    if configured:
        # An explicit configuration never silently selects a different install.
        path = Path(configured).expanduser()
        return path if (path / "GJ_GameSheet.plist").is_file() else None
    home = Path.home()
    steam_roots = [
        home / "Steam",
        home / ".steam/steam",
        home / ".local/share/Steam",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ]
    if os.environ.get("PROGRAMFILES(X86)"):
        steam_roots.append(Path(os.environ["PROGRAMFILES(X86)"]) / "Steam")
    libraries = list(steam_roots)
    for root in steam_roots:
        vdf = root / "steamapps/libraryfolders.vdf"
        if vdf.is_file():
            libraries.extend(
                Path(p.replace("\\\\", "\\"))
                for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text())
            )
    for root in libraries:
        path = root / "steamapps/common/Geometry Dash/Resources"
        if (path / "GJ_GameSheet.plist").is_file():
            return path
    return None


def _numbers(value):
    return [int(n) for n in re.findall(r"-?\d+", value)]


def crop_frame(sheet, entry):
    """Decode Cocos format 3, restoring source size and trimming offsets."""
    from PIL import Image

    x, y, width, height = _numbers(entry["textureRect"])
    rotated = entry.get("textureRotated", False)
    sw, sh = (height, width) if rotated else (width, height)
    if min(x, y) < 0 or min(width, height) <= 0 or x + sw > sheet.width or y + sh > sheet.height:
        raise ValueError("Sprite frame lies outside its original atlas")
    image = sheet.crop((x, y, x + sw, y + sh))
    if rotated:
        image = image.transpose(Image.Transpose.ROTATE_90)
    source_w, source_h = _numbers(entry.get("spriteSourceSize", f"{{{width},{height}}}"))
    if not (0 < source_w <= 4096 and 0 < source_h <= 4096):
        raise ValueError("Invalid original sprite dimensions")
    dx, dy = _numbers(entry.get("spriteOffset", "{0,0}"))
    canvas = Image.new("RGBA", (source_w, source_h))
    canvas.paste(image, ((source_w - width) // 2 + dx, (source_h - height) // 2 - dy))
    return canvas


@lru_cache(maxsize=2)
def _pack(root):
    from PIL import Image

    result = {}

    def add(identifier, image):
        output = io.BytesIO()
        image.save(output, format="PNG")
        result[identifier] = (output.getvalue(), image.size)

    for sheet_name in ("GJ_GameSheet", "GJ_GameSheet02"):
        with (root / f"{sheet_name}.plist").open("rb") as stream:
            frames = plistlib.load(stream)["frames"]
        with Image.open(root / f"{sheet_name}.png") as source:
            sheet = source.convert("RGBA")
            for ident, name in WORLD_FRAMES.items():
                if name in frames:
                    add(ident, crop_frame(sheet, frames[name]))
    for ident, (sheet, name) in ICON_FRAMES.items():
        path = root / "icons" / f"{sheet}_01.plist"
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            frames = plistlib.load(stream)["frames"]
        with Image.open(path.with_suffix(".png")) as source:
            if name in frames:
                add(ident, crop_frame(source.convert("RGBA"), frames[name]))
    for ident, name in {
        "background": "game_bg_01_001.png",
        "ground": "groundSquare_01_001.png",
    }.items():
        if (root / name).is_file():
            with Image.open(root / name) as source:
                add(ident, source.convert("RGBA"))
    return result


def pack():
    try:
        root = resources_path()
        if root is None:
            return {}
        return _pack(root)
    except (ImportError, OSError, ValueError, KeyError, plistlib.InvalidFileException):
        # Optional art must never break simulation or text spectators.
        return {}


def asset(identifier, digest=None):
    data, _ = pack()[identifier]
    version = hashlib.sha256(data).hexdigest()[:24]
    if digest is not None and digest != version:
        raise KeyError("Asset version no longer installed")
    return data, "image/png", version


def manifest():
    assets = {}
    for ident, (data, _) in pack().items():
        version = hashlib.sha256(data).hexdigest()[:24]
        assets[ident] = {
            "url": f"/api/v1/games/geometrydash/assets/{version}/{ident}",
            "version": version,
            "bytes": len(data),
            "media_type": "image/png",
            "scale_mode": "nearest",
        }
    return {"protocol": 1, "game": "geometrydash", "assets": assets}
