"""GDShare .gmd and .gmd2 import, with explicit lossy physics conversion.

Never executes level-provided data or extracts archive members to disk.
"""

from __future__ import annotations

import base64
import plistlib
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

PORTALS = {
    12: "cube",
    13: "ship",
    47: "ball",
    111: "ufo",
    660: "wave",
    745: "robot",
    1331: "spider",
    1931: "swing",
    10: "gravity_normal",
    11: "gravity_reverse",
    99: "normal_size",
    101: "mini",
    286: "dual_on",
    287: "dual_off",
    45: "mirror_on",
    46: "mirror_off",
    200: "speed_slow",
    201: "speed_normal",
    202: "speed_fast",
    203: "speed_faster",
    1334: "speed_very_fast",
}
ORBS = {
    36: "yellow",
    141: "pink",
    1333: "red",
    84: "blue",
    1022: "green",
    1330: "black",
    1704: "dash_green",
    1751: "dash_pink",
}
PADS = {35: "yellow", 140: "pink", 1332: "red", 67: "blue"}
# Only a conservative known-solid/hazard subset. Unrecognized decoration, slopes,
# moving objects, and triggers remain visible in the import report as unsupported.
SPIKES = {8, 39, 103, 392, 393, 394, 395, 396, 397, 398, 399}
BLOCKS = {1, 2, 3, 4, 5, 6, 7}
MAX_FILE = 24 * 1024 * 1024
MAX_UNPACKED = 32 * 1024 * 1024


@dataclass
class ImportedLevel:
    name: str
    objects: list[dict]
    hazards: dict[int, str] = field(default_factory=dict)
    portals: dict[int, object] = field(default_factory=dict)
    pads: dict[int, str] = field(default_factory=dict)
    orbs: dict[int, str] = field(default_factory=dict)
    unsupported: dict[int, int] = field(default_factory=dict)
    collisions: int = 0
    length: int = 40

    def report(self):
        return {
            "name": self.name,
            "objects": len(self.objects),
            "simulated_hazards": len(self.hazards),
            "simulated_portals": len(self.portals),
            "simulated_pads": len(self.pads),
            "simulated_orbs": len(self.orbs),
            "overlapping_objects": self.collisions,
            "unsupported_ids": self.unsupported,
            "length": self.length,
            "limitations": "Approximate one-dimensional projection; no authoritative GD hitboxes, custom triggers, rotations, slopes or dual physics.",
        }


def _data(path):
    path = Path(path)
    if path.stat().st_size > MAX_FILE:
        raise ValueError("level file too large")
    if path.suffix.lower() == ".gmd2":
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("level.data")
            if info.file_size > MAX_UNPACKED:
                raise ValueError("level.data too large")
            return archive.read(info)
    if path.suffix.lower() != ".gmd":
        raise ValueError("expected .gmd or .gmd2")
    return path.read_bytes()


def _decode_payload(encoded):
    if isinstance(encoded, bytes):
        encoded = encoded.decode("utf-8")
    # GD k4 can be stored either as a raw editor string or base64 + zlib.
    if encoded.startswith("kS38,") or encoded.startswith("1,"):
        return encoded
    raw = base64.urlsafe_b64decode(encoded.strip() + "=" * (-len(encoded.strip()) % 4))
    obj = zlib.decompressobj(15 + 32)
    result = obj.decompress(raw, MAX_UNPACKED + 1)
    if len(result) > MAX_UNPACKED or obj.unconsumed_tail:
        raise ValueError("decoded level too large")
    return (result + obj.flush()).decode("utf-8")


def _entries(text):
    # k4 is the semicolon-delimited Geometry Dash editor object string.
    # First entry holds level settings; later entries contain key-value pairs.
    for raw in text.split(";"):
        if not raw:
            continue
        chunks = raw.split(",")
        if len(chunks) < 2:
            continue
        d = dict(zip(chunks[::2], chunks[1::2]))
        if "1" not in d:
            continue
        try:
            yield {
                "id": int(d["1"]),
                "x": float(d.get("2", 0)),
                "y": float(d.get("3", 0)),
                "raw": d,
            }
        except ValueError:
            continue


def load_level(path, *, tile_width=30):
    if tile_width <= 0:
        raise ValueError("tile_width must be positive")
    raw = _data(path)
    if len(raw) > MAX_UNPACKED:
        raise ValueError("input too large")
    try:
        plist = plistlib.loads(raw)
    except Exception as exc:
        raise ValueError("invalid GDShare plist") from exc
    if not isinstance(plist, dict):
        raise ValueError("invalid plist root")
    # Modern exports typically have root at top level; older formats can nest it.
    if isinstance(plist.get("root"), dict):
        plist = plist["root"]
    name = str(plist.get("k2", "Unnamed GDShare level"))
    payload = plist.get("k4")
    if not isinstance(payload, (bytes, str)) or not payload:
        raise ValueError("missing k4 level data")
    objects = list(_entries(_decode_payload(payload)))
    result = ImportedLevel(name, objects)
    omitted = Counter()
    for obj in objects:
        ident = obj["id"]
        x = int(round(obj["x"] / tile_width))
        if x < 0:
            continue
        # Projection is deliberately lossy: x-only scoring, with coarse y bands.
        # Editor uses y=105 as ground line in traditional levels.
        y = obj["y"]
        dest = None
        value = None
        if ident in PORTALS:
            dest = result.portals
            value = PORTALS[ident]
        elif ident in PADS:
            dest = result.pads
            value = PADS[ident]
        elif ident in ORBS:
            dest = result.orbs
            value = ORBS[ident]
        elif ident in SPIKES and 75 <= y <= 135:
            dest = result.hazards
            value = "^"
        elif ident in SPIKES and y >= 225:
            dest = result.hazards
            value = "v"
        elif ident in BLOCKS and 75 <= y <= 135:
            dest = result.hazards
            value = "^"
        else:
            omitted[ident] += 1
        if dest is not None:
            if x in dest:
                result.collisions += 1
            dest[x] = value
    result.unsupported = dict(omitted.most_common())
    result.length = max(40, int(max((o["x"] for o in objects), default=0) / tile_width) + 8)
    return result
