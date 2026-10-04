"""The loop engine: turns Azure DevOps events into decisions and side effects. No Azure SDK imports — everything
external (Azure DevOps, the triage model, the clock) is injected, so the whole loop runs in tests and in the simulator.

Events handled (the Function App maps HTTP bodies straight onto `handle`):
  workitem.created / workitem.updated      service hook from Azure Boards
  ai.dev.result                            posted by dev-agent.yml  {workItemId, status, prUrl?, tokensIn?, tokensOut?}
  ai.qa.started                            posted by deploy-test.yml before it queues the QA agent {workItemId}
  ai.qa.verdict                            posted by qa-agent.yml   {workItemId, verdict, newBugs, failSignature?, tokens*}
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ports import AdoPort, tags_of
from routing import (Decision, ItemView, is_final, on_dev_result, on_qa_started, on_qa_verdict, on_triage_result,
                     on_work_item_event, over_budget, oscillating, started_at, tokens_used, with_failures, with_iteration, with_tokens)

log = logging.getLogger("loop")

TriageFn = Callable[[dict, list], dict]


@dataclass
class EngineConfig:
    iteration_cap: int = 3
    token_budget: int = 2_000_000
    wallclock_s: int = 4 * 3600
    dev_pipeline_id: int = 0
    qa_pipeline_id: int = 0
    agent_identities: frozenset[str] = frozenset()
    human_owner: str = ""


@dataclass
class Outcome:
    status: str                       # ok | ignored | error
    decisions: list[Decision] = field(default_factory=list)
    note: str = ""


class LoopEngine:
    def __init__(self, ado: AdoPort, triage: TriageFn, cfg: EngineConfig | None = None, clock: Callable[[], float] = time.time):
        self.ado, self.triage, self.cfg, self.clock = ado, triage, cfg or EngineConfig(), clock

    # ---- views ---------------------------------------------------------------------------------------
    def view(self, wid: int) -> ItemView:
        wi = self.ado.get_work_item(wid)
        f = wi["fields"]
        return ItemView(id=wid, type=f.get("System.WorkItemType", ""), state=f.get("System.State", ""),
                        tags=tags_of(wi), open_child_bugs=len(self.ado.open_child_bugs(wid)))

    # ---- applying decisions --------------------------------------------------------------------------
    def apply(self, item: ItemView, d: Decision) -> None:
        tags = [t for t in item.tags if t not in d.tags_remove]
        for t in d.tags_add:
            if t.startswith("ai-iter:"):
                tags = with_iteration(tags, int(t.split(":")[1]))
            elif t not in tags:
                tags.append(t)
        self.ado.set_tags(item.id, tags)
        item.tags = tags
        if d.state:
            self.ado.set_state(item.id, d.state)
            item.state = d.state
        log.info(json.dumps({"event": "ai_loop_decision", "workItemId": item.id, "action": d.action, "reason": d.reason, "iteration": item.iteration}))

    def escalate(self, item: ItemView, reason: str) -> Decision:
        d = Decision("escalate", tags_add=["ai-escalated"], tags_remove=["ai-owner:dev", "ai-owner:qa", "ai-owner:orchestrator"], reason=reason)
        self.apply(item, d)
        self.ado.add_comment(item.id, f"<b>Orchestrator:</b> Escalated to a human — {reason}.")
        if self.cfg.human_owner:
            self.ado.assign(item.id, self.cfg.human_owner)
        return d

    def _queue_dev(self, item: ItemView, iteration: int) -> None:
        self.ado.queue_pipeline(self.cfg.dev_pipeline_id, {"workItemId": str(item.id), "iteration": str(iteration)})

    def _charge_tokens(self, item: ItemView, body: dict) -> None:
        add = int(body.get("tokensIn") or 0) + int(body.get("tokensOut") or 0)
        if add:
            item.tags = with_tokens(item.tags, tokens_used(item.tags) + add)
            self.ado.set_tags(item.id, item.tags)

    # ---- entry point ---------------------------------------------------------------------------------
    def handle(self, body: dict[str, Any]) -> Outcome:
        event = body.get("eventType", "")
        res = body.get("resource", {}) or {}
        if event in ("workitem.created", "workitem.updated"):
            return self._on_work_item(event, res)
        if event == "ai.dev.result":
            return self._on_dev_result(body)
        if event == "ai.qa.started":
            return self._on_qa_started(body)
        if event == "ai.qa.verdict":
            return self._on_qa_verdict(body)
        return Outcome("ignored", note=f"unhandled event {event!r}")

    def _on_work_item(self, event: str, res: dict) -> Outcome:
        wid = int(res.get("workItemId") or res.get("id"))
        changed_by = ((res.get("revisedBy") or {}).get("uniqueName") or "").lower()
        item = self.view(wid)
        d = on_work_item_event(item, created=event == "workitem.created", changed_by_agent=changed_by in self.cfg.agent_identities)
        if d.action != "triage":
            return Outcome("ignored", [d], d.reason)
        self.apply(item, d)
        wi = self.ado.get_work_item(wid)
        result = self.triage(wi["fields"], self.ado.list_open_bugs(exclude_id=wid))
        self.ado.add_comment(wid, f"<b>Orchestrator:</b> {result.get('comment', '')}")
        route = result.get("route", "needs_info")
        if result.get("risk") == "high" and route == "dev":
            route = "human"  # high-risk work always needs a human co-owner, whatever the model said
        if route == "close_duplicate" and result.get("duplicate_of"):
            self.ado.add_comment(wid, f"<b>Orchestrator:</b> Duplicate of #{result['duplicate_of']}.")
        d2 = on_triage_result(item, bool(result.get("ready")), route)
        if d2.action == "escalate":
            self.escalate(item, d2.reason)
            return Outcome("ok", [d, d2])
        if d2.action == "queue_dev":
            d2.tags_add = list(d2.tags_add) + [f"ai-started:{int(self.clock())}"]
        self.apply(item, d2)
        if d2.action == "queue_dev":
            self._queue_dev(item, 1)
        return Outcome("ok", [d, d2])

    def _on_dev_result(self, body: dict) -> Outcome:
        item = self.view(int(body["workItemId"]))
        if is_final(item):
            return Outcome("ignored", note="item already finished")
        self._charge_tokens(item, body)
        d = on_dev_result(item, str(body.get("status", "")))
        if d.action == "escalate":
            self.escalate(item, d.reason + (f": {body['summary']}" if body.get("summary") else ""))
            return Outcome("ok", [d])
        why = over_budget(item.tags, self.cfg.token_budget, self.cfg.wallclock_s, self.clock())
        if why:
            self.escalate(item, why)
            return Outcome("ok", [d])
        if d.action == "pr_open":
            self.apply(item, d)
            if body.get("prUrl"):
                self.ado.add_comment(item.id, f"<b>Development agent:</b> PR ready for human review: {body['prUrl']}")
        return Outcome("ok", [d])

    def _on_qa_started(self, body: dict) -> Outcome:
        item = self.view(int(body["workItemId"]))
        if is_final(item) or not item.has("ai-loop"):
            return Outcome("ignored", note="not in loop or finished")
        d = on_qa_started(item)
        self.apply(item, d)
        return Outcome("ok", [d])

    def _on_qa_verdict(self, body: dict) -> Outcome:
        item = self.view(int(body["workItemId"]))
        if is_final(item):
            return Outcome("ignored", note="item already finished (duplicate delivery?)")
        self._charge_tokens(item, body)
        verdict, new_bugs = str(body["verdict"]), int(body.get("newBugs", 0))
        sig = str(body.get("failSignature") or "")
        why = over_budget(item.tags, self.cfg.token_budget, self.cfg.wallclock_s, self.clock())
        if why:
            self.escalate(item, why)
            return Outcome("ok", [Decision("escalate", reason=why)])
        if verdict != "pass" and oscillating(item.tags, item.iteration, sig):
            why = "oscillation detected (the same tests failed two iterations ago, passed, and fail again)"
            self.escalate(item, why)
            return Outcome("ok", [Decision("escalate", reason=why)])
        if verdict == "pass" and new_bugs == 0:
            self._close_verified_bugs(item)
        d = on_qa_verdict(item, verdict, new_bugs, self.cfg.iteration_cap)
        if d.action == "queue_dev":
            n = item.iteration + 1
            if sig:
                item.tags = with_failures(item.tags, item.iteration, sig)
            item.tags = with_iteration(item.tags, n)
            self.apply(item, d)
            self._queue_dev(item, n)
        elif d.action == "escalate":
            self.escalate(item, d.reason)
        else:
            self.apply(item, d)
            if d.action == "ready_for_signoff":
                self.ado.add_comment(item.id, "<b>Orchestrator:</b> Exit criteria met — ready for human sign-off.")
        return Outcome("ok", [d])

    def _close_verified_bugs(self, item: ItemView) -> None:
        """A passing QA run re-tested everything: child bugs the QA agent itself raised are verified fixed, so close them.
        Bugs raised by humans stay open and keep blocking sign-off (a human must judge those)."""
        for cid in self.ado.open_child_bugs(item.id):
            if "ai-raised" in tags_of(self.ado.get_work_item(cid)):
                self.ado.set_state(cid, "Closed")
                self.ado.add_comment(cid, "<b>QA agent:</b> verified fixed in the latest passing run; closed.")
        item.open_child_bugs = len(self.ado.open_child_bugs(item.id))

    # ---- periodic sweep (timer trigger) --------------------------------------------------------------
    def sweep(self) -> list[int]:
        """Escalate loop items that blew the wall-clock budget without an event arriving (stuck pipelines)."""
        out = []
        for wid in self.ado.list_loop_items():
            item = self.view(wid)
            if is_final(item) or started_at(item.tags) is None:
                continue
            why = over_budget(item.tags, 0, self.cfg.wallclock_s, self.clock())
            if why:
                self.escalate(item, why)
                out.append(wid)
        return out
