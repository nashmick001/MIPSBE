"""Product-glimpse eval: does Spark understand the real catalog?

Quizzes the model on REAL search results (dumped locally to
.eval_cache/glimpse.json — real store data, never committed) and grades:
junk rejection, size understanding, Swahili order grounding, honesty on
empty results, cross-module awareness.

Usage:  python evals/product_glimpse.py   (needs .env META_* + the dump)
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv() -> dict:
    env: dict = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


class Spark:
    def __init__(self, env: dict) -> None:
        self.base = env["META_API_BASE"].rstrip("/")
        self.key = env["META_API_KEY"]
        self.model = env["META_AGENT_MODEL"]
        self.tokens = 0

    def ask(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2000,
            "reasoning_effort": "low",
        }
        req = urllib.request.Request(
            f"{self.base}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
        self.tokens += (body.get("usage") or {}).get("total_tokens", 0)
        return body["choices"][0]["message"].get("content") or ""


def as_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def main() -> int:
    dump_path = ROOT / ".eval_cache" / "glimpse.json"
    if not dump_path.exists():
        print("missing .eval_cache/glimpse.json (local-only dump, regenerate from the API)")
        return 2
    dump = json.loads(dump_path.read_text())
    shop = dump["modules"]["6"]
    spark = Spark(load_dotenv())
    fails = 0

    def verdict(label: str, ok: bool, detail: str = "") -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail and not ok else ""))

    unga = shop["unga"]["items"]
    maziwa = shop["maziwa"]["items"]

    # Q1: junk rejection — the unga list contains sausages ("unga" in "Hungarian").
    raw = spark.ask(
        "Products (id, name): " + json.dumps(unga)
        + ". Return ONLY a JSON list of ids that are maize meal, maize flour or wheat flour."
    )
    try:
        ids = set(as_json(raw))
        by_id = {p["id"]: p["name"].lower() for p in unga}
        picked = [by_id[i] for i in ids if i in by_id]
        ok = bool(picked) and all("sausage" not in n and "hot dog" not in n and "salami" not in n for n in picked)
        verdict("Q1 junk rejection (flour only)", ok, f"picked {picked}")
    except (ValueError, TypeError) as exc:
        verdict("Q1 junk rejection (flour only)", False, f"unparseable: {raw[:120]} ({exc})")

    # Q2: size understanding — which maziwa are 1 litre?
    raw = spark.ask(
        "Products (id, name): " + json.dumps(maziwa)
        + ". Return ONLY a JSON list of ids that are 1 litre (not 500ml)."
    )
    try:
        ids = set(as_json(raw))
        by_id = {p["id"]: p["name"].lower().replace(" ", "") for p in maziwa}
        want = {i for i, n in by_id.items() if "1l" in n and "500ml" not in n}
        verdict("Q2 one-litre picker", ids == want, f"got {sorted(ids)} want {sorted(want)}")
    except (ValueError, TypeError) as exc:
        verdict("Q2 one-litre picker", False, f"unparseable: {raw[:120]} ({exc})")

    # Q3: Swahili order grounded in real ids.
    raw = spark.ask(
        'Customer says: "nataka unga 2kg na maziwa". Candidates: ' + json.dumps(unga + maziwa)
        + '. Return ONLY JSON like [{"id": 1, "qty": "2kg"}] using candidate ids.'
    )
    try:
        rows = as_json(raw)
        by_id = {p["id"]: p["name"].lower() for p in unga + maziwa}
        names = [by_id.get(r.get("id"), "") for r in rows]
        qtys = [str(r.get("qty", "")).lower() for r in rows]
        ok = (
            len(rows) == 2
            and any("flour" in n or "meal" in n or "exe" in n for n in names)
            and any("maziwa" in n or "milk" in n or "lala" in n for n in names)
            and any("2kg" in q or "2 kg" in q for q in qtys)
        )
        verdict("Q3 swahili order grounding", ok, f"got {rows}")
    except (ValueError, TypeError, AttributeError) as exc:
        verdict("Q3 swahili order grounding", False, f"unparseable: {raw[:120]} ({exc})")

    # Q4: honesty — chapati has zero Grocery results.
    n = dump["modules"]["3"]["chapati"]["total"]
    raw = spark.ask(
        f'A Grocery search for "chapati" returned {n} results. Can the customer get chapati here? '
        "Answer with YES or NO first, then one short line."
    )
    verdict("Q4 honesty on empty results", raw.strip().upper().startswith("NO"), raw.strip()[:120])

    # Q5: cross-module awareness — maziwa absent in Grocery, present in SHOP.
    g = dump["modules"]["3"]["maziwa"]["total"]
    s = shop["maziwa"]["total"]
    raw = spark.ask(
        f'"maziwa" finds {g} products in Grocery but {s} in SHOP. '
        "In one sentence, tell the customer where to look."
    )
    verdict("Q5 cross-module guidance", "shop" in raw.lower(), raw.strip()[:120])

    print(f"total tokens used: {spark.tokens}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
