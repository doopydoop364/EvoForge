import asyncio

import pytest
import torch

textual = pytest.importorskip("textual")
from evoforge.policy import Policy  # noqa: E402
from evoforge.tui import EvoForgeApp  # noqa: E402


def test_textual_app_mounts_and_loads_legacy_population_replay(tmp_path):
    async def scenario():
        app = EvoForgeApp(tmp_path / "runs" / "demo")
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause(0.2)
            assert app.query_one("#experiments") is not None
            assert "never trained" in str(app.query_one("#board").render())
            policy = Policy()
            torch.save(
                {
                    "config": {"game": "snake", "size": 10, "max_steps": 20, "hidden": 64},
                    "generation": 2,
                    "policies": [policy.state_dict()],
                },
                app.directory / "spectator.pt",
            )
            app._load_champion(live=True)
            assert len(app.agents) == 1
            assert "AGENT" in str(app.query_one("#board").render()) or "CHAMPION" in str(
                app.query_one("#agent-board").render()
            )

    asyncio.run(scenario())


pytestmark = pytest.mark.textual
