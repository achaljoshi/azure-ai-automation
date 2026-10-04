"""Turns the QA agent's JSON result into child bugs and posts the verdict to the Orchestrator."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

SEV = {1: "1 - Critical", 2: "2 - High", 3: "3 - Medium", 4: "4 - Low"}


def sev_label(v) -> str:
    try:
        return SEV.get(int(v), "3 - Medium")
    except (TypeError, ValueError):
        return "3 - Medium"


def fail_signature(bugs: list[dict]) -> str:
    """Stable hash of the failing-test set, used by the orchestrator's oscillation detector."""
    keys = sorted(str(b.get("signature") or b.get("test") or b.get("title", "")) for b in bugs)
    return hashlib.sha1("|".join(keys).encode()).hexdigest()[:8] if keys else ""


def file_bugs(ado, work_item: int, res: dict, existing_titles: set[str] | None = None) -> int:
    """Create one child bug per QA defect (skipping exact duplicates by title); returns how many were created."""
    seen = set(existing_titles or ())
    created = 0
    for b in res.get("bugs", []):
        title = ("[AI-QA] " + str(b["title"]).removeprefix("[AI-QA] "))[:250]
        if title in seen:
            continue
        seen.add(title)
        steps = "".join(f"<li>{html.escape(str(s))}</li>" for s in b.get("steps", []))
        repro = (f"<ol>{steps}</ol><p><b>Expected:</b> {html.escape(str(b.get('expected', '')))}</p>"
                 f"<p><b>Actual:</b> {html.escape(str(b.get('actual', '')))}</p>"
                 f"<p><b>Evidence:</b> {html.escape(', '.join(map(str, b.get('evidence', []))))}</p>"
                 f"<p><b>Test:</b> {html.escape(str(b.get('test', '')))} <b>Signature:</b> {html.escape(str(b.get('signature', '')))}</p>")
        ado.create_child_bug(work_item, title, repro, sev_label(b.get("severity", 3)), ["ai-loop", "ai-raised", "ai-owner:dev"])
        created += 1
    return created


def build_event(work_item: int, res: dict, created: int, tokens_in: int = 0, tokens_out: int = 0) -> dict:
    return {"eventType": "ai.qa.verdict", "workItemId": work_item, "verdict": res.get("verdict", "fail"), "newBugs": created,
            "failSignature": fail_signature(res.get("bugs", [])), "tokensIn": tokens_in, "tokensOut": tokens_out}


def main() -> int:
    from ado_client import AdoClient  # imported late so unit tests need no Azure SDK
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-item", type=int, required=True)
    ap.add_argument("--result", required=True)
    ap.add_argument("--orchestrator", required=True)
    a = ap.parse_args()

    res = json.load(open(a.result, encoding="utf-8"))
    ado = AdoClient(os.environ.get("SYSTEM_COLLECTIONURI"), os.environ.get("SYSTEM_TEAMPROJECT"))
    existing = {b["title"] for b in ado.list_open_bugs(exclude_id=a.work_item)}
    created = file_bugs(ado, a.work_item, res, existing)
    ado.add_comment(a.work_item, f"<b>QA agent:</b> {html.escape(res.get('summary', ''))} (new bugs: {created})")
    ev = build_event(a.work_item, res, created, int(os.environ.get("TOKENSIN", 0) or 0), int(os.environ.get("TOKENSOUT", 0) or 0))
    requests.post(a.orchestrator, json=ev, timeout=30).raise_for_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
