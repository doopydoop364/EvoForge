import pytest
from evoforge.dashboard import _settings_defaults, _change_setting, _validate_settings

def test_choice_changes_wrap_around():
    config=_settings_defaults()
    assert config['game']=='snake'
    _change_setting(config,'game',-1)
    assert config['game']=='flappy'
    _change_setting(config,'game',1)
    assert config['game']=='snake'

def test_numeric_changes_clamp():
    config=_settings_defaults()
    config['population']=2
    _change_setting(config,'population',-1)
    assert config['population']==2

def test_invalid_ppo_candidates_rejected():
    config=_settings_defaults()
    config['population']=4
    config['ppo_candidates']=5
    with pytest.raises(ValueError):_validate_settings(config)

def test_default_settings_valid():
    _validate_settings(_settings_defaults())
