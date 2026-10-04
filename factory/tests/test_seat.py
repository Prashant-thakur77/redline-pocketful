from pathlib import Path

import pytest

from factory import seat as runtime
from factory.seats import load_seats

REPO = Path(__file__).resolve().parents[2]
SEATS = load_seats()
OPEN = SEATS["adversary"].model_copy(update={"harness": "OpenCode", "provider": "google", "model": "gemma-4-31b-it"})


def test_opencode_seat_never_waits_for_a_human():
    cfg = runtime.opencode_config(OPEN, REPO, None, "gemma-4-31b-it", "http://127.0.0.1:4096")
    assert cfg["approval_mode"] == "auto_accept" and cfg["question_mode"] == "auto_reject"
    assert cfg["provider_id"] == "google" and cfg["directory"] == str(REPO)
    assert cfg["custom_section"].startswith("Harness: ")


def test_codex_seat_never_asks_and_is_sandboxed_to_the_repo():
    cfg = runtime.codex_config(SEATS["verifier"], REPO, None, "gpt-5.5")
    assert cfg["approval_policy"] == "never" and cfg["approval_mode"] == "auto_decline"
    assert cfg["workspace_for_room"]("any-room") == str(REPO) and "cwd" not in cfg
    policy = cfg["sandbox_policy"]
    assert policy["type"] == "workspace-write" and str(REPO) in policy["writableRoots"] and policy["networkAccess"]
    assert cfg["custom_section"].startswith("Harness: ")


def test_claude_seat_is_dont_ask_with_allowlist():
    cfg = runtime.claude_config(SEATS["builder"], REPO, Path("/kick"), "claude-sonnet-5")
    assert cfg["permission_mode"] == "dontAsk" and cfg["cwd"] == str(REPO) and cfg["effort"] == "medium"
    assert cfg["setting_sources"] == ("project",) and cfg["cli"]["add_dirs"] == ("/kick",)
    rules = runtime.claude_settings(REPO)["permissions"]
    assert "Bash(docker:*)" in rules["allow"] and "Bash(git push:*)" in rules["deny"]
    assert not any(r.startswith("Bash(rm:") for r in rules["allow"])


def test_fallback_and_ollama_model_split():
    assert runtime.split_model(OPEN, "ollama:qwen3:8b") == ("ollama", "qwen3:8b")
    assert runtime.split_model(OPEN, "gemma-4-31b-it") == ("google", "gemma-4-31b-it")
    models = ["a", "b"]
    assert runtime.next_model(models, 0, "429 Too Many Requests") == (1, 60.0)
    assert runtime.next_model(models, 1, "usage limit reached") == (1, 60.0)
    assert runtime.next_model(models, 0, "connection reset") == (0, 10.0)


def test_relative_repo_rejected():
    with pytest.raises(ValueError):
        runtime.opencode_config(OPEN, Path("result"), None, "m", "http://x")


def test_configs_accepted_by_band_sdk():
    pytest.importorskip("band.adapters.opencode.config")
    from band.adapters import ClaudeSDKAdapterConfig, OpencodeAdapterConfig
    from band.adapters.claude_sdk import ClaudeCLIOptions
    from band.adapters.codex import CodexAdapterConfig
    OpencodeAdapterConfig(**runtime.opencode_config(OPEN, REPO, None, "gemma-4-31b-it", "http://x"))
    from band.adapters.codex import CodexAdapter
    CodexAdapter(config=CodexAdapterConfig(**runtime.codex_config(SEATS["redline"], REPO, None, "gpt-5.5")))
    cfg = runtime.claude_config(SEATS["planner"], REPO, None, "claude-opus-5")
    cfg["cli"] = ClaudeCLIOptions(**cfg["cli"])
    ClaudeSDKAdapterConfig(**cfg)
