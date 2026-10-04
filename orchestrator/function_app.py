"""Orchestrator Function: receives Azure DevOps service hooks and drives the agent loop."""
from __future__ import annotations

import json
import logging
import os

import azure.functions as func

from ado_client import AdoClient
from routing import ItemView, on_qa_verdict, on_triage_result, on_work_item_event, with_iteration
from triage import triage

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
CAP = int(os.environ.get("ITERATION_CAP", "3"))
AGENT_IDENTITIES = {s.strip().lower() for s in os.environ.get("AGENT_IDENTITIES", "").split(",") if s.strip()}


def _view(ado: AdoClient, wid: int) -> ItemView:
    wi = ado.get_work_item(wid)
    f = wi["fields"]
    tags = [t.strip() for t in f.get("System.Tags", "").split(";") if t.strip()]
    return ItemView(id=wid, type=f.get("System.WorkItemType", ""), state=f.get("System.State", ""),
                    tags=tags, open_child_bugs=len(ado.open_child_bugs(wid)))


def _apply(ado: AdoClient, item: ItemView, d) -> None:
    tags = [t for t in item.tags if t not in d.tags_remove]
    for t in d.tags_add:
        if t.startswith("ai-iter:"):
            tags = with_iteration(tags, int(t.split(":")[1]))
        elif t not in tags:
            tags.append(t)
    ado.set_tags(item.id, tags)
    if d.state:
        ado.set_state(item.id, d.state)
    logging.info(json.dumps({"event": "ai_loop_decision", "workItemId": item.id,
                             "action": d.action, "reason": d.reason, "iteration": item.iteration}))


@app.route(route="ado-events", methods=["POST"])
def ado_events(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_json()
    event = body.get("eventType", "")
    res = body.get("resource", {})
    ado = AdoClient()

    if event in ("workitem.created", "workitem.updated"):
        wid = int(res.get("workItemId") or res.get("id"))
        changed_by = (res.get("revisedBy") or {}).get("uniqueName", "").lower()
        item = _view(ado, wid)
        d = on_work_item_event(item, created=event == "workitem.created",
                               changed_by_agent=changed_by in AGENT_IDENTITIES)
        if d.action == "triage":
            wi = ado.get_work_item(wid)
            result = triage(wi["fields"], open_bugs=[])
            ado.add_comment(wid, f"<b>Orchestrator:</b> {result.get('comment', '')}")
            d2 = on_triage_result(item, bool(result.get("ready")), result.get("route", "needs_info"))
            _apply(ado, item, d2)
            if d2.action == "queue_dev":
                ado.queue_pipeline(int(os.environ["DEV_AGENT_PIPELINE_ID"]),
                                   {"workItemId": str(wid), "iteration": "1"})
        return func.HttpResponse("ok")

    if event == "ms.vss-pipelines.run-state-changed-event":
        # deploy-test finished: the QA pipeline is queued per linked work item by deploy-test.yml itself
        return func.HttpResponse("ok")

    if event == "ai.qa.verdict":  # posted by qa-agent.yml at the end of its run
        wid = int(body["workItemId"])
        item = _view(ado, wid)
        d = on_qa_verdict(item, body["verdict"], int(body.get("newBugs", 0)), CAP)
        if d.action == "queue_dev":
            n = item.iteration + 1
            item.tags = with_iteration(item.tags, n)
            _apply(ado, item, d)
            ado.queue_pipeline(int(os.environ["DEV_AGENT_PIPELINE_ID"]),
                               {"workItemId": str(wid), "iteration": str(n)})
        else:
            _apply(ado, item, d)
            if d.action == "escalate":
                ado.add_comment(wid, f"<b>Orchestrator:</b> Escalated to a human — {d.reason}.")
        return func.HttpResponse("ok")

    return func.HttpResponse("ignored", status_code=202)
