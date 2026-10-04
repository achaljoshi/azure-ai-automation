"""Turns the QA agent's JSON result into child bugs and posts the verdict to the Orchestrator."""
from __future__ import annotations

import argparse
import html
import json
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))
from ado_client import AdoClient  # noqa: E402

SEV = {1: "1 - Critical", 2: "2 - High", 3: "3 - Medium", 4: "4 - Low"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-item", type=int, required=True)
    ap.add_argument("--result", required=True)
    ap.add_argument("--orchestrator", required=True)
    a = ap.parse_args()

    res = json.load(open(a.result, encoding="utf-8"))
    ado = AdoClient(os.environ.get("SYSTEM_COLLECTIONURI"), os.environ.get("SYSTEM_TEAMPROJECT"))
    created = 0
    for b in res.get("bugs", []):
        steps = "".join(f"<li>{html.escape(s)}</li>" for s in b.get("steps", []))
        repro = (f"<ol>{steps}</ol><p><b>Expected:</b> {html.escape(b.get('expected',''))}</p>"
                 f"<p><b>Actual:</b> {html.escape(b.get('actual',''))}</p>"
                 f"<p><b>Evidence:</b> {html.escape(', '.join(b.get('evidence', [])))}</p>"
                 f"<p><b>Test:</b> {html.escape(b.get('test',''))} <b>Signature:</b> {html.escape(b.get('signature',''))}</p>")
        ado.create_child_bug(a.work_item, b["title"][:250], repro, SEV.get(int(b.get("severity", 3)), "3 - Medium"),
                             ["ai-loop", "ai-raised", "ai-owner:dev"])
        created += 1
    ado.add_comment(a.work_item, f"<b>QA agent:</b> {html.escape(res.get('summary',''))} (new bugs: {created})")
    requests.post(a.orchestrator, json={"eventType": "ai.qa.verdict", "workItemId": a.work_item,
                                        "verdict": res.get("verdict", "fail"), "newBugs": created}, timeout=30).raise_for_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
