"""Planned turn loop (not yet implemented):

1. Normalize input (text direct; voice via transcribe; photo via vision).
2. Send conversation + tool schemas to the Meta agent model.
3. Execute returned tool calls against DropMtaaniClient, append results.
4. Repeat until the model answers with no more calls (cap: 8 rounds).
5. Guardrails wrap every step: confirmation before payment calls,
   injection screening on untrusted input, spend-cap accounting.
"""

from __future__ import annotations

from typing import Any


async def run_turn(message: str, session: dict[str, Any]) -> dict[str, Any]:
    """Run one customer turn. Day-2+ work."""
    raise NotImplementedError("agent loop not yet implemented")
