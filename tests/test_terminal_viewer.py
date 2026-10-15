from evoforge.terminal_viewer import TerminalInspector


def test_missing_champion_and_controls(tmp_path):
    viewer = TerminalInspector(tmp_path)
    assert not viewer.models
    viewer.handle(ord(" "))
    assert 0 in viewer.focus_paused
    viewer.handle(ord("+"))
    assert viewer.fps == 8
    viewer.handle(ord("9"))
    assert viewer.selection == 0
    viewer.tick()


def test_terminal_render_missing_checkpoint(tmp_path):
    viewer = TerminalInspector(tmp_path)
    output = []
    viewer.render(
        type("Screen", (), {"getmaxyx": lambda self: (30, 100)})(),
        lambda scr, y, x, msg, *args: output.append(str(msg)),
    )
    assert any("Waiting for a saved champion" in s for s in output)


def test_champion_locked_by_default(tmp_path):
    viewer = TerminalInspector(tmp_path)
    assert viewer.auto_update is False
    original = viewer.last_scan
    viewer.tick()
    assert viewer.last_scan == original
    viewer.handle(ord("u"))
    assert viewer.auto_update is True
    viewer.handle(ord("u"))
    assert viewer.auto_update is False


def test_manual_refresh_control(tmp_path):
    viewer = TerminalInspector(tmp_path)
    viewer.last_scan = 0
    viewer.handle(ord("n"))
    assert viewer.last_scan > 0
    assert viewer.auto_update is False


def test_responsive_multi_layout():
    viewer = TerminalInspector.__new__(TerminalInspector)
    focus, panels = viewer.layout(140, 48, 10, 10, 1)
    assert focus is not None
    assert len(panels) >= 1
    assert all(x + 10 * s < 140 and y + 10 < 48 for _, x, y, s in panels)
    _, fewer = viewer.layout(55, 25, 10, 10, 2)
    assert len(fewer) < len(panels)


def test_controls_only_focused_game(tmp_path):
    from evoforge.snake import Snake

    viewer = TerminalInspector(tmp_path)
    viewer.models = [object(), object(), object()]
    viewer.envs = [Snake() for _ in range(3)]
    viewer.observations = [e.reset(900 + i) for i, e in enumerate(viewer.envs)]
    viewer.handle(ord("2"))
    before = [(e.steps, e.food) for e in viewer.envs]
    viewer.handle(ord("r"))
    after = [(e.steps, e.food) for e in viewer.envs]
    assert before[0] == after[0] and before[1] == after[1]
    viewer.handle(ord(" "))
    assert 2 in viewer.focus_paused and 0 not in viewer.focus_paused
    viewer.handle(ord("]"))
    assert viewer.selection == 0
    viewer.handle(ord("k"))
    assert viewer.mini_scale == 2


def test_sparkline_and_terminal_causes():
    from evoforge.snake import Snake

    assert TerminalInspector.sparkline([]).startswith("(no")
    assert TerminalInspector.sparkline([1, 2, 3]) != ""
    env = Snake()
    env.steps = env.max_steps
    assert TerminalInspector._ending(env) == "timeout"


def test_view_options_do_not_mutate_replays(tmp_path):
    viewer = TerminalInspector(tmp_path)
    viewer.handle(ord("f"))
    assert viewer.focus_only
    viewer.handle(ord("a"))
    assert not viewer.show_analytics
    assert viewer.models == []
