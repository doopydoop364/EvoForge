"""Verify actual layout regions and navigation across terminal sizes."""

import asyncio

import pytest
from textual.widgets import Button, Input, TabbedContent

from evoforge.tui import EvoForgeApp, ResponsiveActions

pytestmark = pytest.mark.textual


@pytest.mark.parametrize("width", [80, 100, 120, 160])
@pytest.mark.parametrize("height", [24, 50])
def test_action_groups_fit_and_spectator_controls_remain_reachable(
    tmp_path, monkeypatch, width, height
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "preferences"))

    async def scenario():
        app = EvoForgeApp(tmp_path / "demo")
        async with app.run_test(size=(width, height)) as pilot:
            for tab_id in ["overview", "experiments-tab", "spectator", "analytics", "settings-tab"]:
                tab = app.query_one(f"#--content-tab-{tab_id}")
                tab.scroll_visible(animate=False, immediate=True)
                await pilot.pause()
                assert await pilot.click(tab)
                await pilot.pause()
                assert app.query_one(TabbedContent).active == tab_id
                pane = app.query_one(f"#{tab_id}")
                groups = list(pane.query(ResponsiveActions))
                assert groups
                all_buttons = []
                for group in groups:
                    buttons = list(group.query_children(Button))
                    assert group.content_size.width > 0, (tab_id, group.region)
                    for button in buttons:
                        assert button.region.width >= 16
                        assert button.content_region.width >= button.get_content_width(
                            group.size, group.size
                        )
                        assert group.content_region.contains_region(button.region)
                    for i, first in enumerate(buttons):
                        for second in buttons[i + 1 :]:
                            assert not first.region.overlaps(second.region)
                    # No empty fixed grid rows reserved below the last button.
                    assert max(b.region.bottom for b in buttons) == group.content_region.bottom
                    all_buttons.extend(buttons)
                for i, first in enumerate(all_buttons):
                    for second in all_buttons[i + 1 :]:
                        assert not first.region.overlaps(second.region)
                if tab_id == "experiments-tab":
                    name = app.query_one("#new-name", Input)
                    assert name.region.width >= width - 6
                    assert not isinstance(name.parent, ResponsiveActions)
                if tab_id == "spectator":
                    controls = app.query_one("#spectator-controls")
                    for button in all_buttons:
                        button.focus()
                        button.scroll_visible(animate=False, immediate=True)
                        await pilot.pause()
                        assert button.has_focus
                        assert button.styles.border_top[0] == "heavy"
                        assert controls.content_region.contains_region(button.region)
                        assert pane.content_region.contains_region(button.region)
                    # Keyboard traversal follows composition order after wrapping.
                    app.query_one("#load-champion", Button).focus()
                    await pilot.press("tab")
                    assert app.query_one("#restart-replay", Button).has_focus

    asyncio.run(scenario())


def test_action_groups_reflow_when_terminal_is_resized(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "preferences"))

    async def scenario():
        app = EvoForgeApp(tmp_path / "demo")
        async with app.run_test(size=(160, 50)) as pilot:
            app.query_one(TabbedContent).active = "spectator"
            app.query_one("#--content-tab-spectator").focus()
            await pilot.pause()
            group = app.query_one("#spectator-controls ResponsiveActions")
            original_height = group.size.height
            for width in [80, 100, 120, 160]:
                await pilot.resize_terminal(width, 50)
                await pilot.pause()
                buttons = list(group.query_children(Button))
                assert all(group.content_region.contains_region(b.region) for b in buttons)
                if width == 80:
                    assert group.size.height > original_height
                if width == 160:
                    assert group.size.height == original_height

    asyncio.run(scenario())
