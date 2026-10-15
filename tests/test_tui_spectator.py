"""Regression tests using persisted frames emitted by real training environments."""

import asyncio
import json
import sqlite3
import time

import pytest
import torch
from textual.widgets import DataTable, Select

from evoforge.policy import Policy
from evoforge.supervisor import Supervisor
from evoforge.supervisor.lifecycle import transition
from evoforge.telemetry import FrameChannel
from evoforge.trainer import Config
from evoforge.tui import EvoForgeApp

pytestmark = pytest.mark.textual


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "preferences"))


@pytest.fixture(scope="module")
def completed_runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("spectator-recordings")
    manager = Supervisor(root)
    for name, horizon in [("trained", 4), ("another", 6)]:
        manager.create(
            name,
            Config(
                game="coin",
                mode="evolution",
                population=2,
                elites=1,
                generations=1,
                ppo_candidates=0,
                eval_episodes=1,
                hidden=8,
                game_config={"horizon": horizon},
            ),
        )
        manager.start(name)
        child = manager.children[name]
        deadline = time.monotonic() + 20
        while manager.inspect(name)["status"] != "COMPLETED":
            assert manager.inspect(name)["status"] != "FAILED"
            assert time.monotonic() < deadline
            time.sleep(0.03)
        child.wait(timeout=5)
        assert FrameChannel.read_existing(root / name)
    return root


def board(app):
    return str(app.query_one("#board").render())


def test_reconnect_displays_saved_frames_without_loading_champion(completed_runs):
    async def scenario():
        path = completed_runs / "trained"
        expected = FrameChannel.read_existing(path)
        for _ in range(2):
            app = EvoForgeApp(path)
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                assert (
                    app.spectator_mode == app.query_one("#spectator-mode", Select).value == "live"
                )
                assert "SAVED AGENT" in board(app) and "Coin:" in board(app)
                assert "champion" not in board(app).lower()
                assert app._frame_cursor == expected[-1]["seq"]
                assert str(path) in str(app.query_one("#replay-note").render())
                assert "saved gameplay frames" in str(app.query_one("#replay-note").render())
                assert not app.agents

    asyncio.run(scenario())


def test_replays_and_mode_switches_remain_consistent(completed_runs):
    async def scenario():
        app = EvoForgeApp(completed_runs / "trained")
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.click("#--content-tab-spectator")
            assert await pilot.click("#load-champion")
            await pilot.pause()
            selector = app.query_one("#spectator-mode", Select)
            assert app.spectator_mode == selector.value == "champion"
            assert len(app.agents) == 1 and "CHAMPION" in board(app)
            champion = app.agents[0]["policy"]
            app._refresh()
            assert app.agents[0]["policy"] is champion
            selector.value = "population"
            await pilot.pause()
            assert app.spectator_mode == selector.value == "population"
            assert len(app.agents) == 2 and "AGENT 0" in board(app)
            assert "CHAMPION" not in board(app)
            selector.value = "live"
            await pilot.pause()
            assert app.spectator_mode == selector.value == "live"
            assert not app.agents and "SAVED AGENT" in board(app)
            before = board(app)
            app._spectator_display()
            assert board(app) == before  # Replay view controls cannot overwrite live frames.
            assert "Selected: CHAMPION" not in str(app.query_one("#agent-board").render())

    asyncio.run(scenario())


def test_opening_another_run_resets_cursor_frames_and_selector(completed_runs):
    async def scenario():
        app = EvoForgeApp(completed_runs / "trained")
        async with app.run_test(size=(120, 50)) as pilot:
            app._load_champion()
            await pilot.pause()
            await pilot.click("#--content-tab-experiments-tab")
            table = app.query_one("#experiments", DataTable)
            row = next(
                i for i in range(table.row_count) if str(table.get_row_at(i)[0]) == "another"
            )
            table.move_cursor(row=row)
            assert await pilot.click("#open-run")
            await pilot.pause()
            assert app.directory == completed_runs / "another"
            assert app.spectator_mode == app.query_one("#spectator-mode", Select).value == "live"
            assert app._live_frames
            assert all(frame["experiment"] == "another" for frame in app._live_frames.values())
            assert app._frame_cursor == FrameChannel.read_existing(app.directory)[-1]["seq"]
            assert str(app.directory) in str(app.query_one("#replay-note").render())

    asyncio.run(scenario())


@pytest.mark.parametrize("game", ["snake", "flappy"])
@pytest.mark.parametrize("mode", ["champion", "population"])
def test_v090_artifacts_load_in_their_own_replay_modes(tmp_path, game, mode):
    path = tmp_path / "legacy"
    path.mkdir()
    config = {"game": game, "size": 10, "max_steps": 8, "hidden": 8}
    (path / "config.json").write_text(json.dumps(config))
    policy = Policy(hidden=8)
    if mode == "champion":
        torch.save({"config": config, "state_dict": policy.state_dict()}, path / "champion.pt")
    else:
        torch.save(
            {
                "config": config,
                "generation": 3,
                "policies": [policy.state_dict(), policy.state_dict()],
            },
            path / "spectator.pt",
        )
        # A damaged champion must not prevent a valid population replay loading.
        (path / "champion.pt").write_bytes(b"interrupted legacy champion")

    async def scenario():
        app = EvoForgeApp(path)
        async with app.run_test(size=(120, 50)) as pilot:
            app.query_one("#spectator-mode", Select).value = mode
            await pilot.pause()
            assert app.spectator_mode == mode
            assert len(app.agents) == (1 if mode == "champion" else 2)
            assert "Could not load" not in board(app)
            assert ("CHAMPION" if mode == "champion" else "AGENT 0") in board(app)
            assert not (path / "telemetry.sqlite").exists()

    asyncio.run(scenario())


def test_empty_states_do_not_leak_replay_errors_into_live_mode(tmp_path):
    async def scenario():
        app = EvoForgeApp(tmp_path / "empty")
        async with app.run_test(size=(120, 50)) as pilot:
            assert "never trained" in board(app)
            selector = app.query_one("#spectator-mode", Select)
            for mode, message in [
                ("champion", "No champion is available"),
                ("population", "No population snapshot is available"),
                ("live", "never trained"),
            ]:
                selector.value = mode
                await pilot.pause()
                assert message in board(app)
            # Exercise lifecycle-dependent empty states without inventing frames.
            with app.manager.database.connect() as db:
                transition(db, "empty", "QUEUED")
                transition(db, "empty", "STARTING")
                transition(db, "empty", "RUNNING")
            app._poll_frames()
            assert "awaiting its first gameplay frame" in board(app)
            assert "champion" not in board(app).lower()
            with app.manager.database.connect() as db:
                transition(db, "empty", "COMPLETED")
            app._poll_frames()
            assert "completed" in board(app) and "no recorded gameplay frames" in board(app)
            assert not (app.directory / "telemetry.sqlite").exists()

    asyncio.run(scenario())


def test_telemetry_read_failures_are_visible(tmp_path):
    async def scenario():
        app = EvoForgeApp(tmp_path / "unreadable")
        async with app.run_test(size=(120, 50)):
            (app.directory / "telemetry.sqlite").write_bytes(b"corrupt database")
            app._poll_frames()
            assert "Cannot read gameplay telemetry" in board(app)
            assert "unreadable" in board(app)
            assert not app.agents

    asyncio.run(scenario())


def test_read_existing_does_not_initialize_or_reconfigure_storage(tmp_path, completed_runs):
    with pytest.raises(sqlite3.OperationalError):
        FrameChannel.read_existing(tmp_path)
    assert not (tmp_path / "telemetry.sqlite").exists()
    # A second reader works while an active writer holds the WAL write lock.
    path = completed_runs / "trained"
    with sqlite3.connect(path / "telemetry.sqlite") as writer:
        writer.execute("BEGIN IMMEDIATE")
        assert FrameChannel.read_existing(path)
        writer.rollback()


def test_real_worker_emits_frames_and_second_ui_reconnects(tmp_path):
    async def scenario():
        root = tmp_path / "runs"
        manager = Supervisor(root)
        manager.create(
            "live-run",
            Config(
                game="coin",
                mode="ppo",
                population=2,
                elites=1,
                generations=1000,
                ppo_candidates=0,
                eval_episodes=1,
                ppo_episodes=1,
                hidden=8,
                game_config={"horizon": 8},
            ),
        )
        try:
            app = EvoForgeApp(root / "live-run")
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.click("#--content-tab-spectator")
                assert await pilot.click("#load-champion")
                await pilot.pause()
                assert app.query_one("#spectator-mode", Select).value == "champion"
                assert "No champion is available" in board(app)
                app.query_one("#spectator-mode", Select).value = "live"
                await pilot.pause()
                await pilot.click("#--content-tab-overview")
                assert await pilot.click("#start")
                deadline = time.monotonic() + 20
                while not app._live_frames:
                    assert time.monotonic() < deadline
                    assert manager.inspect("live-run")["status"] != "FAILED"
                    await pilot.pause(0.1)
                assert "LIVE AGENT" in board(app) and "Coin:" in board(app)
                assert all(f["experiment"] == "live-run" for f in app._live_frames.values())
                assert FrameChannel.read_existing(app.directory)[-1]["seq"] >= app._frame_cursor
            worker = manager.inspect("live-run")["worker"]["identity"]
            second = EvoForgeApp(root / "live-run")
            async with second.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                assert second._live_frames and "LIVE AGENT" in board(second)
                assert second.manager.inspect("live-run")["worker"]["identity"] == worker
        finally:
            if manager.inspect("live-run")["status"] in ("STARTING", "RUNNING", "PAUSED"):
                manager.request("live-run", "stop")
                deadline = time.monotonic() + 20
                while manager.inspect("live-run")["status"] != "STOPPED":
                    assert time.monotonic() < deadline
                    await asyncio.sleep(0.05)

    asyncio.run(asyncio.wait_for(scenario(), timeout=45))
