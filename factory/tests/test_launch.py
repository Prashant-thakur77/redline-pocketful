import json

from factory import launch


def test_opencode_config_reads_keys_from_env_only():
    cfg = launch.opencode_config({"FEATHERLESS_API_KEY": "secret-value"})
    text = json.dumps(cfg)
    assert "secret-value" not in text and "{env:FEATHERLESS_API_KEY}" in text
    assert "{env:GEMINI_API_KEY}" in text and "ollama" in cfg["provider"]
    assert cfg["permission"]["webfetch"] == "deny"


def test_featherless_only_when_key_present():
    assert "featherless" not in launch.opencode_config({})["provider"]
