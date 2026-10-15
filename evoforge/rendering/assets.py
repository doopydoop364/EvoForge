"""Explicit manifest lookup. No request path is interpreted as a filename."""

import hashlib
import inspect
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from evoforge.games import GAMES
from evoforge.sdk.registry import discover

from .schema import Manifest

MAX_ASSET_BYTES = 2 * 1024 * 1024
TYPES = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".json": "application/json",
}
SVG_TAGS = {
    "svg",
    "g",
    "path",
    "rect",
    "circle",
    "ellipse",
    "polygon",
    "polyline",
    "line",
    "title",
    "desc",
}
SVG_ATTRS = {
    "xmlns",
    "viewBox",
    "width",
    "height",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "d",
    "points",
    "fill",
    "stroke",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "opacity",
    "fill-opacity",
    "stroke-opacity",
    "transform",
    "fill-rule",
}


def validate_asset(data, path, media_type):
    if len(data) > MAX_ASSET_BYTES:
        raise ValueError("Asset exceeds 2 MiB")
    if TYPES.get(Path(path).suffix.lower()) != media_type:
        raise ValueError("Asset extension and MIME type differ")
    if media_type == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid PNG signature")
    if media_type == "image/webp" and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        raise ValueError("Invalid WebP signature")
    if media_type == "application/json":
        json.loads(data)
    if media_type == "image/svg+xml":
        if b"<!" in data or b"<?" in data:
            raise ValueError("SVG declarations/entities are forbidden")
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            raise ValueError("Invalid SVG") from exc
        if root.tag.split("}")[-1] != "svg":
            raise ValueError("SVG root required")
        for i, node in enumerate(root.iter()):
            if i > 4096 or node.tag.split("}")[-1] not in SVG_TAGS:
                raise ValueError("Unsupported SVG element")
            for key, value in node.attrib.items():
                if key not in SVG_ATTRS or re.search(
                    r"url\s*\(|javascript:|data:|https?:", value, re.I
                ):
                    raise ValueError("Unsupported SVG attribute or external reference")


def package(game):
    if game in GAMES:
        from .builtin import manifest

        return Path(__file__).parent / "assets", Manifest.model_validate(manifest(game))
    cls = discover().get(game)
    if cls is None:
        raise KeyError(game)
    # Plugin root is defined by installed Python code, never by HTTP input.
    return Path(inspect.getfile(cls)).parent, Manifest.model_validate(cls.get_asset_manifest())


def read_asset(root, asset):
    relative = Path(asset.path)
    if (
        relative.is_absolute()
        or any(p in ("..", ".") for p in relative.parts)
        or "\\" in asset.path
    ):
        raise ValueError("Asset path must stay inside its package")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Asset symlinks are forbidden")
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError("Asset escaped package")
    try:
        if current.stat().st_size > MAX_ASSET_BYTES:
            raise ValueError("Asset exceeds 2 MiB")
        data = current.read_bytes()
    except OSError as exc:
        raise ValueError("Declared plugin asset is missing or unreadable") from exc
    validate_asset(data, asset.path, asset.media_type)
    return data


def asset_response(game, identifier, digest=None):
    root, manifest = package(game)
    if identifier not in manifest.assets:
        raise KeyError(identifier)
    asset = manifest.assets[identifier]
    data = read_asset(root, asset)
    version = hashlib.sha256(data).hexdigest()[:24]
    if digest is not None and digest != version:
        raise KeyError("Asset version no longer installed")
    return data, asset.media_type, version


def public_manifest(game):
    _, manifest = package(game)
    assets = {}
    for identifier in manifest.assets:
        data, media_type, digest = asset_response(game, identifier)
        assets[identifier] = {
            "url": f"/api/v1/games/{game}/assets/{digest}/{identifier}",
            "media_type": media_type,
            "bytes": len(data),
            "version": digest,
            "scale_mode": manifest.assets[identifier].scale_mode,
        }
    return {"protocol": 1, "game": game, "assets": assets}
