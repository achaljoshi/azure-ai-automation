"""Orchestrator Function App: thin HTTP/timer shell around loop.engine (all logic and tests live in engine.py)."""
from __future__ import annotations

import logging
import os

import azure.functions as func

from ado_client import AdoClient
from engine import EngineConfig, LoopEngine
from triage import triage

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def _config() -> EngineConfig:
    return EngineConfig(
        iteration_cap=int(os.environ.get("ITERATION_CAP", "3")),
        token_budget=int(os.environ.get("TOKEN_BUDGET", "2000000")),
        wallclock_s=int(os.environ.get("WALLCLOCK_BUDGET_S", str(4 * 3600))),
        dev_pipeline_id=int(os.environ.get("DEV_AGENT_PIPELINE_ID", "0")),
        qa_pipeline_id=int(os.environ.get("QA_AGENT_PIPELINE_ID", "0")),
        agent_identities=frozenset(s.strip().lower() for s in os.environ.get("AGENT_IDENTITIES", "").split(",") if s.strip()),
        human_owner=os.environ.get("HUMAN_OWNER", ""),
    )


def _engine() -> LoopEngine:
    return LoopEngine(AdoClient(), triage, _config())


@app.route(route="ado-events", methods=["POST"])
def ado_events(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse("invalid JSON", status_code=400)
    try:
        out = _engine().handle(body)
    except Exception:  # noqa: BLE001 - never let a webhook retry-storm: log and return 500 once
        logging.exception("loop engine failed for event %s", body.get("eventType"))
        return func.HttpResponse("error", status_code=500)
    return func.HttpResponse(out.status, status_code=202 if out.status == "ignored" else 200)


@app.timer_trigger(schedule="0 */15 * * * *", arg_name="timer", run_on_startup=False)
def sweep(timer: func.TimerRequest) -> None:
    """Escalate items that exceeded the wall-clock budget without any event (stuck pipeline, lost webhook)."""
    escalated = _engine().sweep()
    if escalated:
        logging.warning("escalated stuck work items: %s", escalated)
