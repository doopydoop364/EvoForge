import asyncio
import time

import pytest
from textual.widgets import DataTable, Input, Select

from evoforge.preferences import load_preferences
from evoforge.supervisor import Supervisor
from evoforge.tui import EvoForgeApp


def test_actual_forms_library_settings_and_theme(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "preferences"))

    async def scenario():
        app = EvoForgeApp(tmp_path / "runs" / "initial")
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.click("#--content-tab-experiments-tab")
            await pilot.pause()
            await pilot.click("#new-name")
            await pilot.press(*list("created"))
            await pilot.click("#new-run")
            await pilot.pause()
            assert app.directory.name == "created"
            assert (app.directory / "config.json").exists()
            app.query_one("#field-game", Select).value = "coin"
            app.query_one("#game-config", Input).value = "{broken"
            await pilot.click("#save-settings")
            await pilot.pause(0.25)
            assert "Invalid" in str(app.query_one("#message").render())
            app.query_one("#game-config", Input).value = '{"horizon": 8}'
            app.query_one("#hidden-widths", Input).value = "12,8"
            await pilot.click("#save-settings")
            await pilot.pause(0.25)
            assert "saved" in str(app.query_one("#message").render())
            assert app.manager.inspect("created")["config"]["hidden"] == [12, 8]
            await pilot.click("#--content-tab-experiments-tab")
            await pilot.pause()
            app.query_one("#new-name", Input).value = "copy"
            app.query_one("#experiments", DataTable).move_cursor(row=0)
            await pilot.click("#duplicate-run")
            await pilot.pause()
            assert (tmp_path / "runs" / "copy" / "config.json").exists()
            app.query_one("#new-name", Input).value = "renamed"
            app.query_one("#experiments", DataTable).move_cursor(row=0)
            await pilot.click("#rename-run")
            await pilot.pause()
            assert (tmp_path / "runs" / "renamed" / "config.json").exists()
            await pilot.click("#archive-run")
            await pilot.pause()
            assert app.manager.inspect("renamed")["archived"] == 1
            app.theme = "textual-light"
            await pilot.pause(1)
            assert load_preferences()["theme"] == "textual-light"
        second = EvoForgeApp(tmp_path / "runs" / "initial")
        async with second.run_test(size=(90, 35)) as pilot:
            await pilot.pause()
            assert str(second.theme) == "textual-light"

    asyncio.run(asyncio.wait_for(scenario(), timeout=45))


def test_real_training_buttons_live_frames_and_reconnection(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "preferences"))

    async def scenario():
        root = tmp_path / "runs"
        app = EvoForgeApp(root / "demo")
        manager = app.manager
        try:
            async with app.run_test(size=(140, 50)) as pilot:
                await pilot.click("#--content-tab-settings-tab")
                await pilot.pause()
                for key, value in {
                    "game": "coin",
                    "mode": "ppo",
                    "population": 2,
                    "elites": 1,
                    "ppo_candidates": 0,
                    "generations": 10000,
                    "eval_episodes": 1,
                    "ppo_episodes": 1,
                    "hidden": 8,
                }.items():
                    app.query_one(f"#field-{key}").value = (
                        value if key in ("game", "mode") else str(value)
                    )
                await pilot.click("#save-settings")
                await pilot.pause()
                await pilot.click("#--content-tab-overview")
                await pilot.pause()
                await pilot.click("#start")
                deadline = time.monotonic() + 20
                while manager.inspect("demo")["status"] != "RUNNING":
                    assert time.monotonic() < deadline
                    await pilot.pause(0.1)
                await pilot.click("#pause")
                await pilot.pause(0.25)
                while manager.inspect("demo")["status"] != "PAUSED":
                    assert time.monotonic() < deadline
                    await pilot.pause(0.1)
                await pilot.click("#pause")
                await pilot.pause(0.25)
                while manager.inspect("demo")["status"] != "RUNNING":
                    await pilot.pause(0.1)
                while not (root / "demo" / "champion.pt").exists():
                    assert time.monotonic() < deadline
                    await pilot.pause(0.1)
                await pilot.click("#--content-tab-spectator")
                await pilot.pause(1)
                assert "LIVE AGENT" in str(app.query_one("#board").render())
                for mode in ("champion", "population", "live"):
                    app.query_one("#spectator-mode", Select).value = mode
                    await pilot.pause(0.2)
                    assert app.spectator_mode == mode
                await pilot.click("#grid-replay")
                await pilot.click("#fast-replay")
                assert app.replay_fps == 8
            assert Supervisor(root).inspect("demo")["status"] == "RUNNING"
            second = EvoForgeApp(root / "demo")
            async with second.run_test(size=(140, 50)) as pilot:
                await pilot.pause()
                await pilot.click("#stop")
                deadline = time.monotonic() + 15
                while manager.inspect("demo")["status"] != "STOPPED":
                    assert time.monotonic() < deadline
                    await pilot.pause(0.1)
        finally:
            row = manager.inspect("demo")
            if row["status"] in ("RUNNING", "PAUSED", "STARTING"):
                manager.request("demo", "stop")
                for _ in range(100):
                    if manager.inspect("demo")["status"] == "STOPPED":
                        break
                    await asyncio.sleep(0.05)

    asyncio.run(asyncio.wait_for(scenario(), timeout=45))


pytestmark = pytest.mark.textual
