"""Geometry Dash capture, original atlas loading, and replay integration."""

import json
import plistlib
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from evoforge.api.app import create_app
from evoforge.games import frame, make_env
from evoforge.geometrydash import MODES, ORB_TYPES, PAD_TYPES, PORTAL_TYPES, SYMBOLS
from evoforge.rendering import gd_assets
from evoforge.rendering.schema import validate_scene
from evoforge.telemetry import FrameChannel
from evoforge.telemetry.recordings import EpisodeRecorder, ReplayStore, generate_replays


def nodes(env):
    data = frame(env)
    assert "render_error" not in data
    return {n["id"]: n for n in data["scene"]["nodes"]}


@pytest.mark.parametrize("mode", MODES)
def test_capture_preserves_physics_rng_text_and_player_state(mode):
    env, control = make_env("geometrydash"), make_env("geometrydash")
    env.reset(42)
    control.reset(42)
    env._change_mode(mode)
    control._change_mode(mode)
    before = env.render()
    rng = json.dumps(env.rng.bit_generator.state)
    for _ in range(3):
        captured = nodes(env)
        assert captured["player"]["asset"] == mode
        original_w, original_h = gd_assets.ICON_SIZES[mode]
        assert captured["player"]["width"] / captured["player"]["height"] == pytest.approx(
            original_w / original_h
        )
        assert f"{SYMBOLS[mode]}  {mode.upper()}" in captured["mode"]["text"]
    assert env.render() == before
    assert json.dumps(env.rng.bit_generator.state) == rng
    actual, expected = env.step(1), control.step(1)
    np.testing.assert_array_equal(actual[0], expected[0])
    assert actual[1:] == expected[1:]
    env.mini, env.gravity, env.direction, env.dual, env.held = True, 1, -1, True, True
    changed = nodes(env)
    assert changed["player"]["scale_x"] == -1 and changed["player"]["scale_y"] == -1
    assert changed["player"]["height"] < captured["player"]["height"]
    assert "flag only" in changed["flags"]["text"] and "held" in changed["state"]["text"]
    assert len([key for key in changed if key == "player"]) == 1
    env.collision = env.done = True
    assert nodes(env)["player"]["color"] == "#ff5050"
    assert nodes(env)["collision"]["text"] == "X"


def test_portals_objects_gaps_mirror_and_dense_capture_budget():
    env = make_env("geometrydash")
    env.hazards = {2: "_", 3: "^", 4: "v"}
    env.portals = dict(enumerate(PORTAL_TYPES))
    env.orbs = dict(enumerate(ORB_TYPES))
    env.pads = dict(enumerate(PAD_TYPES))
    env.triggers = {5: [{"type": "timewarp", "value": 2}, "camera_rotate"]}
    captured = nodes(env)
    assert "ground-2" not in captured
    assert captured["hazard-4"]["scale_y"] == -1
    assert any(n.get("asset") == "portal-ship" for n in captured.values())
    assert any(n.get("text") == "camera_rotate" for n in captured.values())
    assert len(json.dumps(frame(env))) < 65536
    env.mirror = True
    mirrored = nodes(env)
    assert mirrored["player"]["x"] == 640 - captured["player"]["x"]
    assert mirrored["player"]["scale_x"] == -1
    assert mirrored["mode"] == captured["mode"]


def test_imported_2d_reference_keeps_y_transforms_unknown_ids_and_reset(tmp_path, monkeypatch):
    path = tmp_path / "level.gmd"
    path.write_bytes(
        plistlib.dumps(
            {
                "k2": "2D test",
                "k4": "1,1,2,180,3,105;1,1,2,180,3,195,4,1,6,90;1,99999,2,210,3,165;"
                "1,8,2,nan,3,105;1,8,2,240,3,inf;",
            }
        )
    )
    monkeypatch.setenv("EVOFORGE_GMD_LEVEL", str(path))
    env = make_env("geometrydash")
    captured = nodes(env)
    assert len(env.imported_level.objects) == 3
    assert captured["import-0"]["x"] == captured["import-1"]["x"] - 28
    assert captured["import-0"]["y"] > captured["import-1"]["y"]
    assert captured["import-1"]["scale_x"] == -1
    assert captured["import-1"]["rotation"] == pytest.approx(np.pi / 2)
    assert captured["import-2"]["text"] == "99999"
    assert "lossy" in captured["source"]["text"]
    assert "unsupported" in captured["limitations"]["text"]
    monkeypatch.delenv("EVOFORGE_GMD_LEVEL")
    env.reset(42)
    assert env.imported_level is None and env.import_report is None
    assert "Imported" not in nodes(env)["source"]["text"]


def test_dense_import_is_bounded_and_reports_omissions(tmp_path, monkeypatch):
    path = tmp_path / "dense.gmd"
    path.write_bytes(plistlib.dumps({"k4": ";".join("1,1,2,180,3,105" for _ in range(500))}))
    monkeypatch.setenv("EVOFORGE_GMD_LEVEL", str(path))
    env = make_env("geometrydash")
    data = frame(env)
    assert "render_error" not in data
    assert len(json.dumps(data)) < 48 * 1024
    assert "456 visible objects omitted" in nodes(env)["limitations"]["text"]
    validate_scene(data["scene"])


@pytest.mark.parametrize("size", [7, 10, 64, 128])
def test_scene_budget_and_visible_player_in_tall_arenas(size):
    env = make_env("geometrydash", size=size)
    env._change_mode("ship")
    data = frame(env)
    assert "render_error" not in data
    assert len(json.dumps(data)) < 48 * 1024
    assert 0 <= nodes(env)["player"]["y"] <= 344


def test_original_atlas_crop_rotation_offsets_and_bounds():
    Image = pytest.importorskip("PIL.Image")
    # Synthetic pixels exercise the decoder only; no test artwork ships to users.
    sheet = Image.new("RGBA", (4, 4))
    sheet.putpixel((1, 1), (255, 0, 0, 255))
    sheet.putpixel((1, 2), (0, 255, 0, 255))
    image = gd_assets.crop_frame(
        sheet,
        {
            "textureRect": "{{1,1},{2,1}}",
            "textureRotated": True,
            "spriteSourceSize": "{4,3}",
            "spriteOffset": "{0,0}",
        },
    )
    assert image.size == (4, 3)
    assert image.getpixel((1, 1)) == (255, 0, 0, 255)
    assert image.getpixel((2, 1)) == (0, 255, 0, 255)
    with pytest.raises(ValueError, match="outside"):
        gd_assets.crop_frame(sheet, {"textureRect": "{{3,3},{3,3}}"})


def test_original_assets_optional_local_install_and_authenticated_routes(tmp_path, monkeypatch):
    original = gd_assets.pack()
    if original:
        assert set(MODES) <= original.keys()
        assert all(data.startswith(b"\x89PNG") for data, _ in original.values())
    monkeypatch.setenv("EVOFORGE_GD_RESOURCES", str(tmp_path / "missing"))
    assert gd_assets.manifest()["assets"] == {}
    with pytest.raises(KeyError):
        gd_assets.asset("../../secret")
    if not original:
        return
    monkeypatch.delenv("EVOFORGE_GD_RESOURCES")
    with TestClient(create_app(tmp_path, token="test")) as client:
        client.post("/api/v1/session", headers={"Authorization": "Bearer test"})
        manifest = client.get("/api/v1/games/geometrydash/manifest").json()
        url = manifest["assets"]["cube"]["url"]
        response = client.get(url)
        assert response.status_code == 200 and response.content == original["cube"][0]
        assert (
            client.get(url.replace(manifest["assets"]["cube"]["version"], "outdated")).status_code
            == 404
        )
        client.delete("/api/v1/session")
        assert client.get(url).status_code == 401


def test_live_and_persisted_replay_share_actual_captured_scene(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/v1/experiments", json={"id": "gd", "config": {"game": "geometrydash"}})
        env = make_env("geometrydash", max_steps=1)
        _, reward, done, _ = env.step(1)
        assert done
        captured = frame(env)
        payload = {
            "experiment": "gd",
            "agent": "0",
            "episode": "actual",
            "seed": 42,
            "generation": 0,
            "phase": "training",
            "timestamp": time.time(),
            "step": 1,
            "score": env.score,
            "reward": reward,
            "terminated": False,
            "truncated": True,
            "data": captured,
        }
        assert FrameChannel(tmp_path / "gd").publish(payload)
        recorder = EpisodeRecorder(tmp_path / "gd", "geometrydash")
        recorder.submit(payload)
        recorder.close()
        with client.websocket_connect("/api/v1/experiments/gd/spectator") as ws:
            live = ws.receive_json()["frames"][0]
            assert live["data"]["scene"] == captured["scene"]
        store = ReplayStore(tmp_path / "gd")
        recording = store.list()[0]
        result = client.get(f"/api/v1/experiments/gd/replays/{recording['id']}").json()
        assert result["frames"][0]["scene"] == captured["scene"]


@pytest.mark.integration
def test_geometrydash_champion_and_population_replays(tmp_path):
    from evoforge.trainer import Config, Trainer

    cfg = Config(
        game="geometrydash",
        mode="evolution",
        population=4,
        elites=1,
        ppo_candidates=0,
        generations=1,
        eval_episodes=1,
        max_steps=12,
        hidden=8,
    )
    Trainer(cfg, tmp_path).run()
    checkpoint = (tmp_path / "champion.pt").read_bytes()
    for mode in ("champion", "population"):
        records = generate_replays(tmp_path, mode, 123, 2)
        assert len(records) == (1 if mode == "champion" else 2)
        for record in records:
            item = ReplayStore(tmp_path).get(record["id"])
            assert item.frames and item.frames[0].scene
            assert any(n.id == "player" for n in item.frames[0].scene.nodes)
    assert (tmp_path / "champion.pt").read_bytes() == checkpoint
