"""Deterministic routing rules for the agent loop. Pure functions — unit tested."""
from __future__ import annotations

from dataclasses import dataclass, field

LOOP_TAG = "ai-loop"


@dataclass
class ItemView:
    id: int
    type: str            # "Bug" | "User Story"
    state: str
    tags: list[str] = field(default_factory=list)
    open_child_bugs: int = 0

    @property
    def iteration(self) -> int:
        for t in self.tags:
            if t.startswith("ai-iter:"):
                try:
                    return int(t.split(":", 1)[1])
                except ValueError:
                    return 0
        return 0

    def has(self, tag: str) -> bool:
        return tag in self.tags


@dataclass
class Decision:
    action: str          # triage | queue_dev | queue_qa | escalate | ready_for_signoff | ignore
    tags_add: list[str] = field(default_factory=list)
    tags_remove: list[str] = field(default_factory=list)
    state: str | None = None
    reason: str = ""


def with_iteration(tags: list[str], n: int) -> list[str]:
    return [t for t in tags if not t.startswith("ai-iter:")] + [f"ai-iter:{n}"]


def on_work_item_event(item: ItemView, created: bool, changed_by_agent: bool) -> Decision:
    if not item.has(LOOP_TAG) or item.has("ai-escalated") or item.state in ("Closed", "Removed"):
        return Decision("ignore", reason="not in loop or finished")
    if created or (item.has("ai-needs-info") and not changed_by_agent):
        return Decision("triage", tags_add=["ai-owner:orchestrator"], reason="new or updated after needs-info")
    return Decision("ignore", reason="no routing change")


def on_triage_result(item: ItemView, ready: bool, route: str) -> Decision:
    if route == "close_duplicate":
        return Decision("ignore", tags_add=["ai-duplicate"], reason="duplicate")
    if route == "human":
        return Decision("escalate", tags_add=["ai-escalated"], reason="high risk / human needed")
    if not ready or route == "needs_info":
        return Decision("ignore", tags_add=["ai-needs-info"], reason="not ready")
    return Decision("queue_dev", tags_add=["ai-owner:dev", "ai-iter:1"],
                    tags_remove=["ai-needs-info", "ai-owner:orchestrator"], state="Active",
                    reason="ready")


def on_qa_verdict(item: ItemView, verdict: str, new_bugs: int, cap: int) -> Decision:
    if verdict == "environment_issue":
        return Decision("ignore", reason="environment issue; QA will retry once")
    if verdict == "pass" and new_bugs == 0 and item.open_child_bugs == 0:
        return Decision("ready_for_signoff", tags_add=["ai-ready-for-signoff"],
                        tags_remove=["ai-owner:qa"], state="Resolved", reason="exit criteria met")
    if item.iteration >= cap:
        return Decision("escalate", tags_add=["ai-escalated"], reason=f"iteration cap {cap} reached")
    return Decision("queue_dev", tags_add=["ai-owner:dev"], tags_remove=["ai-owner:qa"],
                    state="Active", reason=f"defects found; iteration {item.iteration + 1}")
