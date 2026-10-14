"""Exercise library actions through Textual's real mouse and keyboard dispatch."""

import asyncio

import pytest
from textual.widgets import Button, DataTable

from evoforge.supervisor import Supervisor
from evoforge.supervisor.lifecycle import ACTIVE
from evoforge.trainer import Config
from evoforge.tui import EvoForgeApp

pytestmark = pytest.mark.textual
SIZES = [(80, 24), (140, 50)]


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "preferences"))
    manager = Supervisor(tmp_path / "runs")
    for name, seed in [("alpha", 11), ("middle", 22), ("z-open", 33)]:
        manager.create(name, Config(population=2, elites=1, ppo_candidates=0, seed=seed))
    return manager


async def click(pilot, selector):
    widget = pilot.app.query_one(selector)
    widget.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(widget), selector
    await pilot.pause()


async def destination(pilot, name):
    await click(pilot, "#new-name")
    await pilot.press("ctrl+a", "backspace", *name)


async def select_middle(pilot):
    # Click the first data row, then move without Enter / RowSelected.
    table = pilot.app.query_one("#experiments", DataTable)
    table.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(table, offset=(2, 1))
    await pilot.press("down")
    assert table.get_row_at(table.cursor_row)[0] == "middle"


def selected_name(app):
    table = app.query_one("#experiments", DataTable)
    return table.get_row_at(table.cursor_row)[0]


def message(app):
    return str(app.query_one("#message").render())


def artifacts(manager, name):
    path = manager.path(name)
    files = {
        "checkpoint.pt": b"checkpoint fixture",
        "champion.pt": b"champion fixture",
        "spectator.pt": b"population fixture",
        "metrics.csv": b"generation,best_train\n0,12\n",
        "training.log": b"preserve this log\n",
    }
    for filename, data in files.items():
        (path / filename).write_bytes(data)
    manager.database.sync_metrics(name, [{"generation": 0, "best_train": 12}])
    return files


@pytest.mark.parametrize("size", SIZES)
def test_duplicate_uses_keyboard_highlight_after_refresh(library, size):
    files = artifacts(library, "middle")

    async def scenario():
        app = EvoForgeApp(library.path("z-open"))
        async with app.run_test(size=size) as pilot:
            await click(pilot, "#--content-tab-experiments-tab")
            await select_middle(pilot)
            await click(pilot, "#list-runs")
            assert selected_name(app) == "middle"
            await destination(pilot, "a-copy")
            await click(pilot, "#duplicate-run")
            assert "successful" in message(app)
            assert library.inspect("a-copy")["config"] == library.inspect("middle")["config"]
            assert library.inspect("a-copy")["worker"] is None
            assert library.inspect("a-copy")["status"] == "CREATED"
            assert selected_name(app) == "a-copy"
            assert app._selected_experiment == library.path("a-copy")
            assert app.directory == library.path("z-open")
            for filename, data in files.items():
                assert (library.path("middle") / filename).read_bytes() == data
                assert not (library.path("a-copy") / filename).exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("size", SIZES)
def test_rename_open_run_preserves_data_and_selection(library, size):
    files = artifacts(library, "z-open")
    config = library.inspect("z-open")["config"]

    async def scenario():
        app = EvoForgeApp(library.path("z-open"))
        async with app.run_test(size=size) as pilot:
            await click(pilot, "#--content-tab-experiments-tab")
            assert selected_name(app) == "z-open"
            await destination(pilot, "a-renamed")
            await click(pilot, "#rename-run")
            assert "successful" in message(app)
            assert app.directory == library.path("a-renamed")
            assert not library.path("z-open").exists()
            assert library.inspect("a-renamed")["config"] == config
            for filename, data in files.items():
                assert (app.directory / filename).read_bytes() == data
            with library.database.connect() as db:
                assert db.execute("SELECT experiment FROM metrics").fetchone()[0] == "a-renamed"
            await pilot.press("ctrl+r")
            assert selected_name(app) == "a-renamed"
            assert "a-renamed" in str(app.query_one("#run-info").render())
            assert not library.path("z-open").exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("state", ["CREATED", "STOPPED", "COMPLETED", "FAILED"])
def test_archive_unarchive_selected_run_preserves_data(library, size, state):
    files = artifacts(library, "middle")
    # Persist lifecycle fixtures, without substituting action handlers or the supervisor.
    with library.database.connect() as db:
        db.execute("UPDATE experiments SET status=? WHERE id='middle'", (state,))

    async def scenario():
        app = EvoForgeApp(library.path("z-open"))
        async with app.run_test(size=size) as pilot:
            await click(pilot, "#--content-tab-experiments-tab")
            await select_middle(pilot)
            await pilot.press("ctrl+r")
            await click(pilot, "#archive-run")
            assert library.inspect("middle")["archived"] == 1
            assert library.inspect("alpha")["archived"] == 0
            assert library.inspect("z-open")["archived"] == 0
            assert (library.path("middle") / ".archived").exists()
            assert str(app.query_one("#archive-run", Button).label) == "Unarchive"
            assert selected_name(app) == "middle"
            # Keyboard activation uses the same handler as mouse activation.
            await pilot.pause(0.4)  # Allow Textual's button activation effect to finish.
            await pilot.press("enter")
            await pilot.pause()
            assert library.inspect("middle")["archived"] == 0
            assert not (library.path("middle") / ".archived").exists()
            assert "Unarchive successful" in message(app)
            assert str(app.query_one("#archive-run", Button).label) == "Archive"
            assert library.inspect("middle")["status"] == state
            for filename, data in files.items():
                assert (library.path("middle") / filename).read_bytes() == data

    asyncio.run(scenario())


@pytest.mark.parametrize("state", sorted(ACTIVE))
def test_active_worker_restrictions_are_reported_and_duplicate_is_allowed(library, state):
    # ACTIVE without a process is a deterministic fixture for every persisted state.
    with library.database.connect() as db:
        db.execute("UPDATE experiments SET status=? WHERE id='middle'", (state,))

    async def scenario():
        app = EvoForgeApp(library.path("z-open"))
        async with app.run_test(size=(100, 32)) as pilot:
            await click(pilot, "#--content-tab-experiments-tab")
            await select_middle(pilot)
            await destination(pilot, "copy")
            await click(pilot, "#rename-run")
            assert "Stop the worker" in message(app)
            assert not library.path("copy").exists()
            await click(pilot, "#archive-run")
            assert "Stop the worker" in message(app)
            assert library.inspect("middle")["archived"] == 0
            await click(pilot, "#duplicate-run")
            assert library.inspect("copy")["config"]["seed"] == 22
            assert library.inspect("middle")["status"] == state

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["duplicate", "rename"])
@pytest.mark.parametrize("name", ["", "../escape", "alpha"])
def test_invalid_or_existing_destination_leaves_source_intact(library, action, name):
    original = (library.path("middle") / "config.json").read_bytes()

    async def scenario():
        app = EvoForgeApp(library.path("z-open"))
        async with app.run_test(size=(100, 32)) as pilot:
            await click(pilot, "#--content-tab-experiments-tab")
            await select_middle(pilot)
            await destination(pilot, name)
            await click(pilot, f"#{action}-run")
            assert "failed" in message(app).lower()
            assert (library.path("middle") / "config.json").read_bytes() == original
            assert library.inspect("alpha")["config"]["seed"] == 11
            assert selected_name(app) == "middle"
            assert not (library.root.parent / "escape").exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("size", SIZES)
def test_library_table_and_actions_remain_reachable_after_resize(library, size):
    async def scenario():
        app = EvoForgeApp(library.path("z-open"))
        async with app.run_test(size=(140, 50)) as pilot:
            await click(pilot, "#--content-tab-experiments-tab")
            await pilot.resize_terminal(*size)
            await pilot.pause()
            table = app.query_one("#experiments", DataTable)
            assert table.content_size.height >= 4  # header plus the three library rows
            for selector in ["#open-run", "#duplicate-run", "#rename-run", "#archive-run"]:
                button = app.query_one(selector, Button)
                button.focus()
                await pilot.pause()
                assert app.query_one("#experiments-tab").content_region.contains_region(
                    button.region
                )
            await select_middle(pilot)
            await click(pilot, "#open-run")
            assert app.directory == library.path("middle")

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["rename", "archive"])
def test_worker_lock_still_prevents_edits_even_with_inactive_state(library, action):
    import fcntl

    async def scenario():
        app = EvoForgeApp(library.path("z-open"))
        async with app.run_test(size=(100, 32)) as pilot:
            await click(pilot, "#--content-tab-experiments-tab")
            await select_middle(pilot)
            await destination(pilot, "renamed")
            with (library.path("middle") / ".worker.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                await click(pilot, f"#{action}-run")
                assert "Stop the worker" in message(app)
            assert library.path("middle").exists()
            assert not library.path("renamed").exists()
            assert library.inspect("middle")["archived"] == 0

    asyncio.run(scenario())


def test_empty_table_cannot_act_on_stale_selection(library):
    async def scenario():
        app = EvoForgeApp(library.path("z-open"))
        async with app.run_test(size=(100, 32)) as pilot:
            await click(pilot, "#--content-tab-experiments-tab")
            await select_middle(pilot)
            await destination(pilot, "copy")
            app.query_one("#experiments", DataTable).clear()
            for action in ["duplicate", "rename", "archive"]:
                await click(pilot, f"#{action}-run")
                assert "Select an experiment first" in message(app)
            assert not library.path("copy").exists()
            assert library.inspect("middle")["archived"] == 0

    asyncio.run(scenario())
