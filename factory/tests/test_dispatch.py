import pytest

from factory.dispatch import body_of, render


def test_render_fills_placeholders_and_refuses_gaps():
    text = body_of("intro\n```text\n@Planner build in {{REPO}} from {{KICKOFF}}\n```\n")
    assert render(text, {"REPO": "/r", "KICKOFF": "/k"}) == "@Planner build in /r from /k"
    with pytest.raises(ValueError):
        render(text, {"REPO": "/r"})


def test_smoke_reply_matching():
    from types import SimpleNamespace as M

    from factory.smoke import replied
    msgs = [M(sender_id="a", message_type="text", content="token abc123"),
            M(sender_id="b", message_type="error", content="abc999")]
    assert replied(msgs, "a", "abc123") and not replied(msgs, "b", "abc999") and not replied(msgs, "a", "zzz")


def test_watch_lines_hide_evidence_and_mentions():
    from factory.watch import lines
    items = [{"message_type": "text", "inserted_at": "2026-10-04T09:34:34Z", "sender_name": "Verifier",
              "content": "@[[x]] GO\n```json\n{\"a\": 1}\n```"},
             {"message_type": "tool_call", "content": "ignored"}]
    assert lines(items, 10) == ["09:34:34 Verifier: @ GO [evidence]"]


def test_second_dispatch_is_refused(tmp_path, capsys):
    from factory import dispatch
    record = tmp_path / "toy"
    record.write_text("room-1\n")
    plan = tmp_path / "d.md"
    plan.write_text("```text\n@Planner go\n```\n")
    assert dispatch.main([str(plan), "--title", "t", "--save-room", str(record)]) == 1
    assert "rerun" in capsys.readouterr().err
