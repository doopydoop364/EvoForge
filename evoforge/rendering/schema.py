"""Renderer protocol v1. Bounded, finite, declarative data only."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]
Number = Annotated[float, Field(allow_inf_nan=False, ge=-1_000_000, le=1_000_000)]
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Camera(Model):
    x: Number = 0
    y: Number = 0
    zoom: float = Field(1, ge=0.1, le=10)


class Animation(Model):
    frames: list[Identifier] = Field(min_length=1, max_length=120)
    fps: float = Field(8, gt=0, le=60)


class Node(Model):
    id: Identifier
    kind: Literal["sprite", "rect", "text", "tilemap"]
    x: Number = 0
    y: Number = 0
    width: float = Field(32, gt=0, le=8192)
    height: float = Field(32, gt=0, le=8192)
    rotation: Number = 0
    scale_x: float = Field(1, ge=-10, le=10)
    scale_y: float = Field(1, ge=-10, le=10)
    layer: int = Field(0, ge=-100, le=100)
    visible: bool = True
    opacity: float = Field(1, ge=0, le=1)
    asset: Identifier | None = None
    animation: Identifier | None = None
    text: str = Field("", max_length=1024)
    color: Color = "#ffffff"
    font_size: int = Field(20, ge=8, le=144)
    hud: bool = False
    columns: int = Field(1, ge=1, le=128)
    tiles: list[int] = Field(default_factory=list, max_length=16384)
    palette: list[Identifier] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def tile_indices(self):
        if self.kind == "tilemap" and (
            not self.palette or any(i < -1 or i >= len(self.palette) for i in self.tiles)
        ):
            raise ValueError("tilemap indices must reference its palette, or -1 for empty")
        return self


class Scene(Model):
    protocol: Literal[1] = 1
    width: int = Field(640, ge=16, le=4096)
    height: int = Field(480, ge=16, le=4096)
    coordinates: Literal["y-down", "y-up"] = "y-down"
    background: Color = "#112622"
    timestamp: float = Field(0, ge=0)
    camera: Camera | None = None
    nodes: list[Node] = Field(default_factory=list, max_length=4096)
    animations: dict[Identifier, Animation] = Field(default_factory=dict, max_length=64)

    @model_validator(mode="after")
    def complexity(self):
        if len({n.id for n in self.nodes}) != len(self.nodes):
            raise ValueError("Scene node identifiers must be unique")
        if sum(len(n.tiles) if n.kind == "tilemap" else 1 for n in self.nodes) > 16384:
            raise ValueError("Scene exceeds 16384 rendered elements")
        if any(n.animation and n.animation not in self.animations for n in self.nodes):
            raise ValueError("Unknown animation identifier")
        return self


def validate_scene(value):
    if len(json.dumps(value, allow_nan=False).encode()) > 262144:
        raise ValueError("Scene exceeds 256 KiB")
    scene = Scene.model_validate(value).model_dump()
    if len(json.dumps(scene, allow_nan=False).encode()) > 48 * 1024:
        raise ValueError("Normalized scene exceeds 48 KiB telemetry presentation budget")
    return scene


class Asset(Model):
    path: str = Field(min_length=1, max_length=200)
    media_type: Literal["image/png", "image/webp", "image/svg+xml", "application/json"]


class Manifest(Model):
    protocol: Literal[1] = 1
    assets: dict[Identifier, Asset] = Field(default_factory=dict, max_length=256)
