"""Thin Azure DevOps REST client used where the Remote MCP Server lacks a write operation.

Auth: managed identity / workload identity via azure-identity. No PATs.
"""
from __future__ import annotations

import os
from typing import Any

import requests
from azure.identity import DefaultAzureCredential

ADO_RESOURCE = "499b84ac-1321-427f-aa17-267ca6975798/.default"  # Azure DevOps app ID
API = "7.1"


class AdoClient:
    def __init__(self, org_url: str | None = None, project: str | None = None):
        self.org = (org_url or os.environ["ADO_ORG_URL"]).rstrip("/")
        self.project = project or os.environ["ADO_PROJECT"]
        self._cred = DefaultAzureCredential()

    def _headers(self, content_type: str = "application/json") -> dict[str, str]:
        token = self._cred.get_token(ADO_RESOURCE).token
        return {"Authorization": f"Bearer {token}", "Content-Type": content_type}

    def _url(self, path: str) -> str:
        return f"{self.org}/{self.project}/_apis/{path}"

    # --- work items -------------------------------------------------------
    def get_work_item(self, wid: int) -> dict[str, Any]:
        r = requests.get(self._url(f"wit/workitems/{wid}?$expand=relations&api-version={API}"),
                         headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()

    def patch_work_item(self, wid: int, ops: list[dict[str, Any]]) -> dict[str, Any]:
        r = requests.patch(self._url(f"wit/workitems/{wid}?api-version={API}"), json=ops,
                           headers=self._headers("application/json-patch+json"), timeout=30)
        r.raise_for_status()
        return r.json()

    def set_tags(self, wid: int, tags: list[str]) -> None:
        self.patch_work_item(wid, [{"op": "add", "path": "/fields/System.Tags", "value": "; ".join(sorted(set(tags)))}])

    def set_state(self, wid: int, state: str) -> None:
        self.patch_work_item(wid, [{"op": "add", "path": "/fields/System.State", "value": state}])

    def assign(self, wid: int, user: str) -> None:
        self.patch_work_item(wid, [{"op": "add", "path": "/fields/System.AssignedTo", "value": user}])

    def add_comment(self, wid: int, text: str) -> None:
        r = requests.post(self._url(f"wit/workItems/{wid}/comments?api-version={API}-preview.4"),
                          json={"text": text}, headers=self._headers(), timeout=30)
        r.raise_for_status()

    def create_child_bug(self, parent_id: int, title: str, repro_html: str, severity: str, tags: list[str]) -> int:
        ops = [
            {"op": "add", "path": "/fields/System.Title", "value": title},
            {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.ReproSteps", "value": repro_html},
            {"op": "add", "path": "/fields/Microsoft.VSTS.Common.Severity", "value": severity},
            {"op": "add", "path": "/fields/System.Tags", "value": "; ".join(tags)},
            {"op": "add", "path": "/relations/-", "value": {
                "rel": "System.LinkTypes.Hierarchy-Reverse",
                "url": f"{self.org}/_apis/wit/workItems/{parent_id}"}},
        ]
        r = requests.post(self._url(f"wit/workitems/$Bug?api-version={API}"), json=ops,
                          headers=self._headers("application/json-patch+json"), timeout=30)
        r.raise_for_status()
        return r.json()["id"]

    def wiql(self, query: str) -> list[int]:
        r = requests.post(self._url(f"wit/wiql?api-version={API}"), json={"query": query},
                          headers=self._headers(), timeout=30)
        r.raise_for_status()
        return [w["id"] for w in r.json().get("workItems", [])]

    def open_child_bugs(self, parent_id: int) -> list[int]:
        q = ("SELECT [System.Id] FROM WorkItemLinks WHERE "
             f"([Source].[System.Id] = {parent_id}) AND "
             "([System.Links.LinkType] = 'System.LinkTypes.Hierarchy-Forward') AND "
             "([Target].[System.WorkItemType] = 'Bug') AND "
             "([Target].[System.State] NOT IN ('Closed', 'Removed')) MODE (MustContain)")
        r = requests.post(self._url(f"wit/wiql?api-version={API}"), json={"query": q},
                          headers=self._headers(), timeout=30)
        r.raise_for_status()
        rels = r.json().get("workItemRelations", [])
        return [x["target"]["id"] for x in rels if x.get("source")]

    # --- pipelines --------------------------------------------------------
    def queue_pipeline(self, pipeline_id: int, params: dict[str, str]) -> int:
        r = requests.post(self._url(f"pipelines/{pipeline_id}/runs?api-version={API}"),
                          json={"templateParameters": params}, headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()["id"]
