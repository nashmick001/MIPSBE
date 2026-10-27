"""Day-1 provider check: key works, models listed, Spark understands Swahili.

Reads META_* from .env (never pass keys on the command line).
Usage:  python scripts/check_provider.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path


def load_dotenv(path: Path) -> dict:
    env: dict = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    env = load_dotenv(root / ".env")
    base = env.get("META_API_BASE", "").rstrip("/")
    key = env.get("META_API_KEY", "")
    if not base or not key:
        print("META_API_BASE / META_API_KEY missing from .env")
        return 1

    def call(path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload else None
        req = urllib.request.Request(
            f"{base}{path}",
            data=data,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())

    models = call("/models")
    ids = sorted(m.get("id", "?") for m in models.get("data", []))
    print("models:", ", ".join(ids))

    agent_model = env.get("META_AGENT_MODEL", "")
    if agent_model not in ids:
        print(f"META_AGENT_MODEL={agent_model!r} is not in the enabled list")
        return 1

    chat = call(
        "/chat/completions",
        {
            "model": agent_model,
            "messages": [
                {
                    "role": "user",
                    "content": 'Nataka unga 2kg na maziwa. Reply with ONLY a JSON list like [{"item": "...", "qty": "..."}].',
                }
            ],
            "max_tokens": 2000,
            "reasoning_effort": "low",
        },
    )
    content = chat["choices"][0]["message"].get("content")
    if content:
        print("swahili-test:", content.strip())
    else:
        print("swahili-test: EMPTY content, raw choice:")
        print(json.dumps(chat["choices"][0], indent=1)[:1500])
    print("usage:", chat.get("usage"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
