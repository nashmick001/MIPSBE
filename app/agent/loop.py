"""Turn loop: model replies or calls tools, tools run, repeat until answered.

History is client-managed (the chat response returns the updated turns), so
the service stays stateless. Every tool call lands in `trace` for the demo
trace panel. Cap: 8 model rounds per turn.
"""

from __future__ import annotations

import json
from typing import Any

from app.agent.meta import MetaClient, MetaError
from app.agent.prompts import SYSTEM_PROMPT
from app.tools.catalog import TOOL_SCHEMAS, execute_tool
from app.tools.dropmtaani import CustomerContext, DropMtaaniClient

MAX_ROUNDS = 8


async def run_turn(
    message: str,
    history: list[dict],
    ctx: CustomerContext,
    meta: MetaClient,
    client: DropMtaaniClient,
) -> dict[str, Any]:
    """Run one customer turn. Returns reply + trace + updated history."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": t["role"], "content": t["content"]} for t in history]
    messages.append({"role": "user", "content": message})

    trace: list[dict] = []
    try:
        for _ in range(MAX_ROUNDS):
            answer = await meta.chat(messages, tools=TOOL_SCHEMAS)
            calls = answer.get("tool_calls") or []
            if not calls:
                reply = answer.get("content") or ""
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": answer.get("content"),
                    "tool_calls": [
                        {
                            "id": c.get("id"),
                            "type": "function",
                            "function": c.get("function", {}),
                        }
                        for c in calls
                    ],
                }
            )
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await execute_tool(name, args, ctx, client)
                trace.append({"tool": name, "args": args, "ok": "error" not in result})
                messages.append(
                    {"role": "tool", "tool_call_id": call.get("id"), "content": json.dumps(result)}
                )
        else:
            reply = "That took too many steps — could you ask in a simpler way?"
    except MetaError:
        reply = "I'm having trouble reaching my AI service right now. Please try again."

    new_history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    return {"reply": reply, "trace": trace, "history": new_history}
