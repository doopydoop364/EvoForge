"""Presentation, assets, browser sessions and persistent replay contracts."""

import time

import pytest
from fastapi.testclient import TestClient

from evoforge.api.app import create_app
from evoforge.games import close_env, frame, make_env
from evoforge.rendering.assets import asset_response, public_manifest, read_asset, validate_asset
from evoforge.rendering.schema import Asset, Scene, validate_scene
from evoforge.telemetry.recordings import EpisodeRecorder, Recording, ReplayStore


@pytest.mark.parametrize("game", ["snake", "flappy", "coin"])
def test_scene_assets_and_simulation_are_independent(game):
    left, right = make_env(game), make_env(game)
    try:
        left.reset(7)
        right.reset(7)
        for _ in range(3):
            before = left.render()
            data = frame(left)
            assert data["text"] == before
            scene = Scene.model_validate(data["scene"])
            assert scene.protocol == 1 and scene.nodes
            assert left.render() == right.render()
            manifest = public_manifest(game)
            for value in manifest["assets"].values():
                assert value["url"].startswith(f"/api/v1/games/{game}/assets/")
            if left.done:
                break
            left.step(1)
            right.step(1)
    finally:
        close_env(left)
        close_env(right)


@pytest.mark.parametrize(
    "patch",
    [
        {"protocol": 2},
        {"width": 999999},
        {"camera": {"x": float("nan")}},
        {"nodes": [{"id": "a", "kind": "html"}]},
        {"nodes": [{"id": "a", "kind": "text", "text": "x" * 1025}]},
        {"nodes": [{"id": "a", "kind": "rect", "animation": "missing"}]},
    ],
)
def test_invalid_scene_is_rejected(patch):
    with pytest.raises(ValueError):
        validate_scene({"protocol": 1, **patch})


def test_scene_duplicate_ids_and_complexity():
    node = {"id": "a", "kind": "rect"}
    with pytest.raises(ValueError, match="unique"):
        validate_scene({"nodes": [node, node]})
    with pytest.raises(ValueError, match="256 KiB"):
        validate_scene({"nodes": [{**node, "text": "x" * 300000}]})
    with pytest.raises(ValueError):
        validate_scene(
            {"nodes": [{"id": "a", "kind": "tilemap", "palette": ["tile"], "tiles": [1]}]}
        )


@pytest.mark.parametrize(
    "svg",
    [
        b"<svg><script>alert(1)</script></svg>",
        b'<svg onload="alert(1)"/>',
        b"<svg><foreignObject/></svg>",
        b"<!DOCTYPE svg><svg/>",
        b'<svg><image href="https://example.com/a.png"/></svg>',
        b'<svg><rect fill="url(https://example.com/a)"/></svg>',
    ],
)
def test_active_svg_rejected(svg):
    with pytest.raises(ValueError):
        validate_asset(svg, "a.svg", "image/svg+xml")


def test_assets_reject_paths_symlinks_mime_and_oversize(tmp_path):
    for name in ("../secret.svg", "/etc/passwd", "..\\secret.svg"):
        with pytest.raises(ValueError):
            read_asset(tmp_path, Asset(path=name, media_type="image/svg+xml"))
    (tmp_path / "link.svg").symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="symlink"):
        read_asset(tmp_path, Asset(path="link.svg", media_type="image/svg+xml"))
    for data, path, mime in [
        (b"<svg/>", "a.png", "image/svg+xml"),
        (b"hello", "a.png", "image/png"),
        (b"x" * (2 * 1024 * 1024 + 1), "a.svg", "image/svg+xml"),
    ]:
        with pytest.raises(ValueError):
            validate_asset(data, path, mime)
    with pytest.raises(KeyError):
        asset_response("snake", "head", "outdated")
    with pytest.raises(KeyError):
        asset_response("snake", "not-declared")


def recording(identifier="a" * 32):
    return {
        "id": identifier,
        "run": "test",
        "game": "coin",
        "game_version": "1.0.0",
        "agent": "0",
        "episode": "episode-1",
        "source": "training",
        "created": 1.0,
        "frames": [
            {"seq": 1, "timestamp": 1.0, "step": 1, "score": 0.0, "reward": -1.0},
            {"seq": 2, "timestamp": 1.1, "step": 2, "score": 1.0, "reward": 1.0, "truncated": True},
        ],
    }


def test_recording_roundtrip_compatibility_order_and_retention(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOFORGE_REPLAY_EPISODES", "2")
    store = ReplayStore(tmp_path)
    for letter in "abc":
        store.save(recording(letter * 32))
    assert len(store.list()) == 2
    assert store.get("c" * 32).frames[1].reward == 1
    assert not (tmp_path / "replays" / ("a" * 32 + ".json")).exists()
    with pytest.raises(ValueError):
        Recording.model_validate({**recording(), "format_version": 2})
    data = recording()
    data["frames"].reverse()
    with pytest.raises(ValueError, match="ordered"):
        Recording.model_validate(data)
    with pytest.raises(KeyError):
        store.get("../../secret")


def test_browser_session_asset_auth_origin_and_limits(tmp_path):
    app = create_app(tmp_path, token="test-token")
    with TestClient(app) as client:
        assert client.get("/api/v1/dashboard").status_code == 401
        assert (
            client.post("/api/v1/session", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
        login = client.post("/api/v1/session", headers={"Authorization": "Bearer test-token"})
        assert login.status_code == 200
        assert (
            "HttpOnly" in login.headers["set-cookie"]
            and "SameSite=strict" in login.headers["set-cookie"]
        )
        assert client.get("/api/v1/dashboard").status_code == 200
        assert (
            client.post(
                "/api/v1/experiments",
                json={"id": "owned"},
                headers={"Origin": "https://evil.invalid"},
            ).status_code
            == 403
        )
        assert client.post("/api/v1/experiments", json={"id": "owned"}).status_code == 201
        with client.websocket_connect(
            "/api/v1/events", headers={"Origin": "http://testserver"}
        ) as ws:
            assert ws.receive_json()["events"]
        manifest = client.get("/api/v1/games/snake/manifest").json()
        url = manifest["assets"]["head"]["url"]
        asset = client.get(url)
        assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
        assert asset.headers["x-content-type-options"] == "nosniff"
        assert client.get("/api/v1/games/snake/assets/bad/head").status_code == 404
        assert client.post("/api/v1/experiments", content=b" " * 65537).status_code == 413
        assert (
            client.post("/api/v1/experiments", content="[" * 20 + "0" + "]" * 20).status_code == 422
        )
        assert (
            client.post(
                "/api/v1/experiments", json={"id": "bad", "config": {"hidden": [100000]}}
            ).status_code
            == 422
        )
        assert client.delete("/api/v1/session").status_code == 200
        assert client.get(url).status_code == 401
        assert client.get("/api/v1/health", headers={"Host": "evil.invalid"}).status_code == 400


def test_replay_routes_validate_and_page_frames(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.post("/api/v1/experiments", json={"id": "test"}).status_code == 201
        store = ReplayStore(tmp_path / "test")
        store.save(recording())
        assert client.get("/api/v1/experiments/test/replays").json()[0]["frame_count"] == 2
        page = client.get(
            "/api/v1/experiments/test/replays/" + "a" * 32 + "?offset=1&limit=1"
        ).json()
        assert len(page["frames"]) == 1 and page["frames"][0]["step"] == 2
        assert (
            client.post("/api/v1/experiments/test/replays", json={"mode": "champion"}).status_code
            == 404
        )
        assert (
            client.get("/api/v1/experiments/test/replays/" + "a" * 32 + "?limit=100000").status_code
            == 422
        )
        assert client.get("/api/v1/experiments/test/checkpoints").json() == []
        assert client.get("/api/v1/experiments/test/logs").json()["text"] == ""


def test_async_recorder_persists_actual_episode(tmp_path):
    env = make_env("coin", game_config={"horizon": 2})
    recorder = EpisodeRecorder(tmp_path, "coin")
    env.reset(5)
    try:
        for step in range(2):
            _, reward, done, _ = env.step(1)
            recorder.submit(
                {
                    "episode": "actual",
                    "agent": "0",
                    "seed": 5,
                    "generation": 0,
                    "phase": "training",
                    "timestamp": time.time(),
                    "step": step + 1,
                    "score": env.score,
                    "reward": reward,
                    "terminated": False,
                    "truncated": done,
                    "data": frame(env),
                }
            )
        recorder.close()
        metadata = recorder.store.list()[0]
        item = recorder.store.get(metadata["id"])
        assert len(item.frames) == 2 and item.seed == 5
        assert item.frames[-1].score == env.score and item.frames[-1].scene
    finally:
        close_env(env)


def test_invalid_plugin_presentation_keeps_simulation_working(monkeypatch):
    env = make_env("coin")
    env.reset(8)
    monkeypatch.setattr(env.plugin, "render_scene", lambda: {"protocol": 999})
    try:
        data = frame(env)
        assert "render_error" in data and "Coin:" in data["text"]
        assert env.step(0)[1] in (-1, 1)
    finally:
        close_env(env)


def test_normalized_scene_budget_and_missing_asset_errors(tmp_path):
    with pytest.raises(ValueError, match="48 KiB"):
        validate_scene({"nodes": [{"id": f"node-{i}", "kind": "rect"} for i in range(200)]})
    with pytest.raises(ValueError, match="missing or unreadable"):
        read_asset(tmp_path, Asset(path="missing.svg", media_type="image/svg+xml"))


def test_websocket_cookie_origin_rejection_and_remote_binding(tmp_path, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(ValueError, match="Remote binding"):
        create_app(tmp_path, bind_host="0.0.0.0")
    with TestClient(create_app(tmp_path, token="operator")) as client:
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/api/v1/events"):
                pass
        assert denied.value.code == 4401
        client.post("/api/v1/session", headers={"Authorization": "Bearer operator"})
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect(
                "/api/v1/events", headers={"Origin": "https://evil.invalid"}
            ):
                pass
        assert denied.value.code == 4403
    monkeypatch.setenv("EVOFORGE_ALLOWED_HOSTS", "*")
    with pytest.raises(ValueError, match="Wildcard"):
        create_app(tmp_path)


def test_saved_spectator_frames_follow_renamed_run(tmp_path):
    from evoforge.telemetry import FrameChannel

    app = create_app(tmp_path)
    manager = app.state.supervisor
    manager.create("before", {})
    channel = FrameChannel(tmp_path / "before")
    assert channel.publish(
        {"experiment": "before", "agent": "0", "timestamp": 1.0, "data": {"text": "recorded"}}
    )
    manager.rename("before", "after")
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/experiments/after/spectator") as ws:
            frame = ws.receive_json()["frames"][0]
            assert frame["experiment"] == "after"
            assert frame["recorded_experiment"] == "before"
            assert frame["data"]["text"] == "recorded"
