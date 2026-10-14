from evoforge.preferences import load_preferences, save_preferences


def test_preferences_round_trip(tmp_path):
    path = tmp_path / "evoforge" / "preferences.json"
    assert load_preferences(path) == {}
    save_preferences({"theme": "textual-dark"}, path)
    assert load_preferences(path)["theme"] == "textual-dark"
    save_preferences({"other": 2}, path)
    assert load_preferences(path) == {"theme": "textual-dark", "other": 2}


def test_bad_preferences_are_ignored(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("not json")
    assert load_preferences(path) == {}
