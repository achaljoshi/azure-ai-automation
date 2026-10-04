"""Builds context.json for an agent run: the work item, its open child bugs (QA failures) and the iteration number."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))


def build(ado, wid: int, iteration: str, extra: dict | None = None) -> dict:
    wi = ado.get_work_item(wid)["fields"]
    children = []
    for cid in ado.open_child_bugs(wid):
        f = ado.get_work_item(cid)["fields"]
        children.append({"id": cid, "title": f.get("System.Title", ""), "severity": f.get("Microsoft.VSTS.Common.Severity", ""),
                         "repro": f.get("Microsoft.VSTS.TCM.ReproSteps", "")[:4000]})
    ctx = {"work_item": {k: v for k, v in wi.items() if k in ("System.Title", "System.Description", "System.WorkItemType", "System.State", "System.Tags",
                                                               "Microsoft.VSTS.Common.AcceptanceCriteria", "Microsoft.VSTS.TCM.ReproSteps")},
           "open_child_bugs": children, "iteration": iteration}
    ctx.update(extra or {})
    return ctx


def main() -> int:
    from ado_client import AdoClient
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-item", type=int, required=True)
    ap.add_argument("--iteration", default="1")
    ap.add_argument("--out", default="context.json")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--thresholds", default="qa-thresholds.json")
    ap.add_argument("--role", choices=["dev", "qa"], default="dev")
    a = ap.parse_args()
    extra: dict = {}
    if a.role == "qa":
        extra["test_base_url"] = a.base_url
        extra["thresholds"] = json.load(open(a.thresholds, encoding="utf-8")) if os.path.exists(a.thresholds) else {}
    ctx = build(AdoClient(os.environ.get("SYSTEM_COLLECTIONURI"), os.environ.get("SYSTEM_TEAMPROJECT")), a.work_item, a.iteration, extra)
    json.dump(ctx, open(a.out, "w", encoding="utf-8"), indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
