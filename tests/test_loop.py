"""Turn loop: tool rounds run, trace records, failures stay graceful."""

import asyncio
import json

from app.agent.loop import run_turn
from app.agent.meta import MetaError
from app.tools.dropmtaani import CustomerContext


class FakeMeta:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    async def chat(self, messages, tools=None):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def tool_call(name, args, call_id="c1"):
    return {
        "content": None,
        "tool_calls": [
            {"id": call_id, "function": {"name": name, "arguments": json.dumps(args)}}
        ],
    }


def test_tool_round_then_reply(monkeypatch):
    async def fake_execute(name, args, ctx, client):
        return {"items": [{"id": 1, "name": "Unga"}]}

    import app.agent.loop as loop_mod

    monkeypatch.setattr(loop_mod, "execute_tool", fake_execute)
    meta = FakeMeta([tool_call("search_products", {"query": "unga"}), {"content": "Found unga."}])
    out = asyncio.run(run_turn("nataka unga", [], CustomerContext(), meta, object()))
    assert out["reply"] == "Found unga."
    assert out["trace"] == [{"tool": "search_products", "args": {"query": "unga"}, "ok": True}]
    assert [t["role"] for t in out["history"]] == ["user", "assistant"]
    assert meta.calls == 2


def test_meta_failure_is_graceful(monkeypatch):
    import app.agent.loop as loop_mod

    monkeypatch.setattr(loop_mod, "execute_tool", None)
    meta = FakeMeta([MetaError("down")])
    out = asyncio.run(run_turn("hi", [], CustomerContext(), meta, object()))
    assert "trouble" in out["reply"]
    assert out["trace"] == []


def test_round_cap(monkeypatch):
    async def fake_execute(name, args, ctx, client):
        return {"items": []}

    import app.agent.loop as loop_mod

    monkeypatch.setattr(loop_mod, "execute_tool", fake_execute)
    monkeypatch.setattr(loop_mod, "MAX_ROUNDS", 2)
    meta = FakeMeta([tool_call("search_products", {"query": "x"})] * 3)
    out = asyncio.run(run_turn("x", [], CustomerContext(), meta, object()))
    assert "too many steps" in out["reply"]
    assert len(out["trace"]) == 2
