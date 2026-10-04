"""Post a loop event to the Orchestrator Function (used by pipelines: ai.dev.result, ai.qa.started).

    python scripts/post_event.py --url "$ORCHESTRATOR_URL" --type ai.dev.result --work-item 1042 \
        --result agent-result.json --tokens-in "$TOKENSIN" --tokens-out "$TOKENSOUT"
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import requests


def build(event: str, work_item: int, result: dict | None, tokens_in: int, tokens_out: int) -> dict:
    body = {"eventType": event, "workItemId": work_item, "tokensIn": tokens_in, "tokensOut": tokens_out}
    if event == "ai.dev.result" and result is not None:
        body.update({"status": result.get("status", "blocked"), "summary": str(result.get("summary", ""))[:1000], "prUrl": result.get("pr_url", "")})
    return body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--type", required=True, choices=["ai.dev.result", "ai.qa.started"])
    ap.add_argument("--work-item", type=int, required=True)
    ap.add_argument("--result", help="agent-result.json (dev result)")
    ap.add_argument("--tokens-in", type=int, default=int(os.environ.get("TOKENSIN", 0) or 0))
    ap.add_argument("--tokens-out", type=int, default=int(os.environ.get("TOKENSOUT", 0) or 0))
    a = ap.parse_args()
    result = json.load(open(a.result, encoding="utf-8")) if a.result and os.path.exists(a.result) else ({"status": "blocked", "summary": "no result file produced"} if a.type == "ai.dev.result" else None)
    requests.post(a.url, json=build(a.type, a.work_item, result, a.tokens_in, a.tokens_out), timeout=30).raise_for_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
