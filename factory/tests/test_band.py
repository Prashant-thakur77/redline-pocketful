import asyncio
import json

import httpx
import pytest

from factory.band import BandAgent, HandoffError, InterceptingAdapter, MissingSeat, credentials, resolve

ME, PEER = "agent-me", "agent-peer"


def agent(handler):
    return BandAgent("builder", ME, "key", rest_url="https://band.test/",
                     transport=httpx.MockTransport(handler))


def test_send_without_mention_fails_loudly():
    calls = []
    a = agent(lambda r: calls.append(r) or httpx.Response(201, json={}))
    with pytest.raises(HandoffError):
        a.send("room", "done", mentions=[])
    assert calls == []  # nothing reached BAND, and no dummy mention was invented


def test_send_to_self_rejected_before_network():
    a = agent(lambda r: httpx.Response(500))
    with pytest.raises(HandoffError):
        a.send("room", "hi", mentions=[{"id": ME, "handle": "me"}])


def test_send_posts_wrapped_message():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["key"] = request.headers["X-API-Key"]
        return httpx.Response(201, json={"data": {"id": "m1"}})

    agent(handler).send("room", "@verifier ready", [{"id": PEER, "handle": "verifier"}])
    assert seen["body"]["message"]["mentions"][0]["id"] == PEER
    assert seen["key"] == "key"


def test_context_follows_cursor_across_pages():
    pages = {None: ([{"id": "1"}, {"id": "2"}], "c2"), "c2": ([{"id": "3"}], None)}

    def handler(request):
        data, nxt = pages[request.url.params.get("cursor")]
        return httpx.Response(200, json={"data": data,
                                         "metadata": {"next_cursor": nxt, "has_more": nxt is not None}})

    assert [m["id"] for m in agent(handler).context("room")] == ["1", "2", "3"]


def test_http_errors_raise():
    with pytest.raises(httpx.HTTPStatusError):
        agent(lambda r: httpx.Response(422, text="cannot_mention_self")).me()


def test_intercepting_adapter_sees_event_and_survives_callback_errors():
    seen = []

    class Target:
        async def on_event(self, event):
            return f"handled {event}"

    def boom(event):
        seen.append(event)
        raise RuntimeError("observer bug")

    wrapped = InterceptingAdapter(Target(), boom)
    assert asyncio.run(wrapped.on_event("e1")) == "handled e1"
    assert seen == ["e1"]


def test_credentials_have_no_fallback():
    with pytest.raises(MissingSeat):
        credentials("adversary", env={"BAND_AGENT_ID_BUILDER": "x", "BAND_API_KEY_BUILDER": "y"})


def test_resolve_rejects_key_for_another_agent():
    env = {"BAND_AGENT_ID_VERIFIER": "v1", "BAND_API_KEY_VERIFIER": "k",
           "BAND_REST_URL": "https://band.test"}
    other = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {"id": "b1"}}))
    with pytest.raises(MissingSeat):
        resolve("verifier", env, transport=other)
    own = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"data": {"id": "v1", "handle": "acct/verifier", "name": "Verifier",
                            "owner_uuid": "o1"}}))
    assert resolve("verifier", env, transport=own).owner == "o1"
