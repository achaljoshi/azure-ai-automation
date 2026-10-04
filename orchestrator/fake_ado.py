"""In-memory Azure DevOps for tests, the simulator and the local loop. Same surface as AdoClient (see ports.AdoPort)."""
from __future__ import annotations

import itertools
import time
from typing import Any

from ports import tags_of

CLOSED = ("Closed", "Removed")


class FakeAdo:
    def __init__(self) -> None:
        self._ids = itertools.count(1001)
        self.items: dict[int, dict[str, Any]] = {}
        self.comments: dict[int, list[str]] = {}
        self.assigned: dict[int, str] = {}
        self.parents: dict[int, int] = {}
        self.pipeline_runs: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []

    # ---- helpers for tests / simulator --------------------------------------------------------------
    def create(self, type_: str, title: str, tags: list[str] | None = None, state: str = "New", **fields: Any) -> int:
        wid = next(self._ids)
        self.items[wid] = {"id": wid, "fields": {"System.WorkItemType": type_, "System.Title": title, "System.State": state,
                                                  "System.Tags": "; ".join(tags or []), "System.CreatedDate": time.time(), **fields}}
        self.comments[wid] = []
        self._log("create", wid, title=title)
        return wid

    def _log(self, op: str, wid: int, **kw: Any) -> None:
        self.audit.append({"op": op, "id": wid, **kw})

    def tags(self, wid: int) -> list[str]:
        return tags_of(self.items[wid])

    def state(self, wid: int) -> str:
        return self.items[wid]["fields"]["System.State"]

    # ---- AdoPort -------------------------------------------------------------------------------------
    def get_work_item(self, wid: int) -> dict[str, Any]:
        if wid not in self.items:
            raise KeyError(f"work item {wid} not found")
        wi = self.items[wid]
        return {"id": wid, "fields": dict(wi["fields"])}

    def set_tags(self, wid: int, tags: list[str]) -> None:
        self.items[wid]["fields"]["System.Tags"] = "; ".join(sorted(set(tags)))
        self._log("tags", wid, tags=sorted(set(tags)))

    def set_state(self, wid: int, state: str) -> None:
        self.items[wid]["fields"]["System.State"] = state
        self._log("state", wid, state=state)

    def assign(self, wid: int, user: str) -> None:
        self.assigned[wid] = user
        self._log("assign", wid, user=user)

    def add_comment(self, wid: int, text: str) -> None:
        self.comments[wid].append(text)
        self._log("comment", wid, text=text[:120])

    def create_child_bug(self, parent_id: int, title: str, repro_html: str, severity: str, tags: list[str]) -> int:
        wid = self.create("Bug", title, tags, **{"Microsoft.VSTS.TCM.ReproSteps": repro_html, "Microsoft.VSTS.Common.Severity": severity})
        self.parents[wid] = parent_id
        return wid

    def open_child_bugs(self, parent_id: int) -> list[int]:
        return [c for c, p in self.parents.items() if p == parent_id and self.state(c) not in CLOSED]

    def list_open_bugs(self, exclude_id: int | None = None) -> list[dict[str, Any]]:
        return [{"id": i, "title": w["fields"]["System.Title"], "state": w["fields"]["System.State"],
                 "repro": w["fields"].get("Microsoft.VSTS.TCM.ReproSteps", "")}
                for i, w in self.items.items()
                if w["fields"]["System.WorkItemType"] == "Bug" and w["fields"]["System.State"] not in CLOSED and i != exclude_id]

    def list_loop_items(self) -> list[int]:
        return [i for i, w in self.items.items() if "ai-loop" in tags_of(w) and w["fields"]["System.State"] not in CLOSED]

    def queue_pipeline(self, pipeline_id: int, params: dict[str, str]) -> int:
        self.pipeline_runs.append({"pipeline": pipeline_id, "params": dict(params)})
        self._log("queue", int(params.get("workItemId", 0)), pipeline=pipeline_id, params=params)
        return len(self.pipeline_runs)
