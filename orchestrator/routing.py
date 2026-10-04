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


# ---------------------------------------------------------------------------------------------------------
# Additions: dev results, QA start, token / wall-clock budgets, oscillation detection
# ---------------------------------------------------------------------------------------------------------
FINAL_TAGS = ("ai-escalated", "ai-ready-for-signoff", "ai-duplicate")


def is_final(item: ItemView) -> bool:
    return any(item.has(t) for t in FINAL_TAGS) or item.state in ("Closed", "Removed")


def tag_value(tags: list[str], prefix: str) -> str | None:
    for t in tags:
        if t.startswith(prefix + ":"):
            return t.split(":", 1)[1]
    return None


def tokens_used(tags: list[str]) -> int:
    try:
        return int(tag_value(tags, "ai-tokens") or 0)
    except ValueError:
        return 0


def with_tokens(tags: list[str], total: int) -> list[str]:
    return [t for t in tags if not t.startswith("ai-tokens:")] + [f"ai-tokens:{total}"]


def started_at(tags: list[str]) -> float | None:
    try:
        v = tag_value(tags, "ai-started")
        return float(v) if v else None
    except ValueError:
        return None


def over_budget(tags: list[str], token_budget: int, wallclock_s: int, now: float) -> str | None:
    if token_budget and tokens_used(tags) > token_budget:
        return f"token budget {token_budget:,} exceeded ({tokens_used(tags):,} used)"
    st = started_at(tags)
    if wallclock_s and st and now - st > wallclock_s:
        return f"wall-clock budget {wallclock_s // 3600}h exceeded"
    return None


def with_failures(tags: list[str], iteration: int, signature: str) -> list[str]:
    """Remember a hash of the failing-test set per iteration (keep the last 4)."""
    kept = [t for t in tags if t.startswith("ai-fail:")]
    kept = sorted(kept, key=lambda t: int(t.split(":")[1]))[-3:]
    return [t for t in tags if not t.startswith("ai-fail:")] + kept + [f"ai-fail:{iteration}:{signature}"]


def oscillating(tags: list[str], iteration: int, signature: str) -> bool:
    """Same failing set seen two iterations ago (fail -> different -> fail again) means the agent is flip-flopping."""
    if not signature:
        return False
    for t in tags:
        if t.startswith("ai-fail:"):
            _, n, sig = t.split(":", 2)
            if int(n) <= iteration - 2 and sig == signature:
                return True
    return False


def on_dev_result(item: ItemView, status: str) -> Decision:
    if status == "blocked":
        return Decision("escalate", tags_add=["ai-escalated"], tags_remove=["ai-owner:dev"], reason="dev agent blocked")
    if status in ("pr_opened", "pr_updated"):
        return Decision("pr_open", tags_add=["ai-pr-open"], reason=status)
    return Decision("ignore", reason=f"unknown dev status {status!r}")


def on_qa_started(item: ItemView) -> Decision:
    return Decision("qa_started", tags_add=["ai-owner:qa"], tags_remove=["ai-owner:dev", "ai-pr-open"], state="Resolved", reason="qa started")
