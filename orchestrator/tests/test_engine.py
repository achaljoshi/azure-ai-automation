"""End-to-end loop scenarios on the engine with an in-memory Azure DevOps. No network, no Azure SDKs."""
from engine import EngineConfig, LoopEngine
from fake_ado import FakeAdo

READY = {"ready": True, "route": "dev", "risk": "low", "comment": "Looks good."}


def make(triage=None, **cfg):
    ado = FakeAdo()
    clock = {"t": 1_000_000.0}
    eng = LoopEngine(ado, triage or (lambda wi, bugs: dict(READY)), EngineConfig(dev_pipeline_id=7, qa_pipeline_id=8, human_owner="boss@example.com", **cfg), clock=lambda: clock["t"])
    return ado, eng, clock


def created(wid):
    return {"eventType": "workitem.created", "resource": {"workItemId": wid, "revisedBy": {"uniqueName": "human@example.com"}}}


def bug(ado, **kw):
    return ado.create("Bug", "Login fails", ["ai-loop"], **kw)


def qa(wid, verdict, new_bugs=0, **kw):
    return {"eventType": "ai.qa.verdict", "workItemId": wid, "verdict": verdict, "newBugs": new_bugs, **kw}


def test_ready_bug_is_triaged_and_queued_for_dev():
    ado, eng, _ = make()
    w = bug(ado)
    out = eng.handle(created(w))
    assert out.status == "ok"
    assert "ai-owner:dev" in ado.tags(w) and "ai-iter:1" in ado.tags(w) and any(t.startswith("ai-started:") for t in ado.tags(w))
    assert ado.state(w) == "Active"
    assert ado.pipeline_runs == [{"pipeline": 7, "params": {"workItemId": str(w), "iteration": "1"}}]
    assert any("Orchestrator" in c for c in ado.comments[w])


def test_item_without_loop_tag_is_ignored():
    ado, eng, _ = make()
    w = ado.create("Bug", "x", [])
    assert eng.handle(created(w)).status == "ignored" and not ado.pipeline_runs


def test_needs_info_then_human_update_retriages():
    answers = [{"ready": False, "route": "needs_info", "risk": "low", "comment": "Add repro steps."}, dict(READY)]
    ado, eng, _ = make(lambda wi, bugs: answers.pop(0))
    w = bug(ado)
    eng.handle(created(w))
    assert "ai-needs-info" in ado.tags(w) and not ado.pipeline_runs
    upd = {"eventType": "workitem.updated", "resource": {"workItemId": w, "revisedBy": {"uniqueName": "human@example.com"}}}
    eng.handle(upd)
    assert "ai-needs-info" not in ado.tags(w) and len(ado.pipeline_runs) == 1


def test_agent_edits_do_not_retrigger_triage():
    ado, eng, _ = make(lambda wi, bugs: {"ready": False, "route": "needs_info", "risk": "low", "comment": "x"})
    eng.cfg.agent_identities = frozenset({"agent@example.com"})
    w = bug(ado)
    eng.handle(created(w))
    out = eng.handle({"eventType": "workitem.updated", "resource": {"workItemId": w, "revisedBy": {"uniqueName": "Agent@Example.com"}}})
    assert out.status == "ignored"


def test_high_risk_is_forced_to_a_human_even_if_model_says_dev():
    ado, eng, _ = make(lambda wi, bugs: {"ready": True, "route": "dev", "risk": "high", "comment": "Touches auth."})
    w = bug(ado)
    eng.handle(created(w))
    assert "ai-escalated" in ado.tags(w) and ado.assigned[w] == "boss@example.com" and not ado.pipeline_runs


def test_duplicate_is_closed_out_of_loop():
    ado, eng, _ = make(lambda wi, bugs: {"ready": True, "route": "close_duplicate", "duplicate_of": 5, "risk": "low", "comment": "dup"})
    w = bug(ado)
    eng.handle(created(w))
    assert "ai-duplicate" in ado.tags(w) and not ado.pipeline_runs and any("Duplicate of #5" in c for c in ado.comments[w])


def test_triage_sees_other_open_bugs_but_not_itself():
    seen = {}
    ado, eng, _ = make(lambda wi, bugs: seen.setdefault("bugs", bugs) and dict(READY) or dict(READY))
    other = ado.create("Bug", "Other bug", ["ai-loop"])
    w = bug(ado)
    eng.handle(created(w))
    assert [b["id"] for b in seen["bugs"]] == [other]


def full_loop_to_pass(ado, eng, w):
    eng.handle(created(w))
    eng.handle({"eventType": "ai.dev.result", "workItemId": w, "status": "pr_opened", "prUrl": "http://pr/1"})
    eng.handle({"eventType": "ai.qa.started", "workItemId": w})


def test_happy_path_bug_through_two_iterations_to_signoff():
    ado, eng, _ = make()
    w = bug(ado)
    full_loop_to_pass(ado, eng, w)
    assert ado.state(w) == "Resolved" and "ai-owner:qa" in ado.tags(w) and "ai-pr-open" not in ado.tags(w)
    child = ado.create_child_bug(w, "[AI-QA] regression", "<ol/>", "2 - High", ["ai-loop", "ai-raised"])
    eng.handle(qa(w, "fail", 1, failSignature="aaaa"))
    assert "ai-iter:2" in ado.tags(w) and ado.state(w) == "Active" and len(ado.pipeline_runs) == 2
    assert ado.pipeline_runs[-1]["params"]["iteration"] == "2"
    eng.handle({"eventType": "ai.qa.started", "workItemId": w})
    eng.handle(qa(w, "pass", 0))
    assert ado.state(child) == "Closed"                       # verified fixed by the passing run
    assert "ai-ready-for-signoff" in ado.tags(w) and ado.state(w) == "Resolved"


def test_pass_with_open_child_bug_does_not_sign_off():
    ado, eng, _ = make()
    w = bug(ado)
    full_loop_to_pass(ado, eng, w)
    human_bug = ado.create_child_bug(w, "Reported by a person", "", "3 - Medium", ["ai-loop"])   # not ai-raised: only a human may close it
    eng.handle(qa(w, "pass", 0))
    assert "ai-ready-for-signoff" not in ado.tags(w) and ado.state(human_bug) != "Closed"


def test_iteration_cap_escalates_to_human():
    ado, eng, _ = make(iteration_cap=2)
    w = bug(ado)
    full_loop_to_pass(ado, eng, w)
    eng.handle(qa(w, "fail", 1, failSignature="a"))     # -> iter 2
    eng.handle(qa(w, "fail", 1, failSignature="b"))     # cap reached
    assert "ai-escalated" in ado.tags(w) and ado.assigned[w] == "boss@example.com"
    assert len(ado.pipeline_runs) == 2                  # no third dev run


def test_oscillation_escalates_immediately():
    ado, eng, _ = make(iteration_cap=9)
    w = bug(ado)
    full_loop_to_pass(ado, eng, w)
    eng.handle(qa(w, "fail", 1, failSignature="aaa"))   # iter1 fails with A -> iter 2
    eng.handle(qa(w, "fail", 1, failSignature="bbb"))   # iter2 fails with B -> iter 3
    out = eng.handle(qa(w, "fail", 1, failSignature="aaa"))  # iter3 fails with A again
    assert "ai-escalated" in ado.tags(w) and "oscillation" in out.decisions[0].reason


def test_environment_issue_does_not_loop_or_escalate():
    ado, eng, _ = make()
    w = bug(ado)
    full_loop_to_pass(ado, eng, w)
    n = len(ado.pipeline_runs)
    eng.handle(qa(w, "environment_issue", 0))
    assert len(ado.pipeline_runs) == n and "ai-escalated" not in ado.tags(w)


def test_duplicate_verdict_delivery_is_idempotent():
    ado, eng, _ = make()
    w = bug(ado)
    full_loop_to_pass(ado, eng, w)
    eng.handle(qa(w, "pass", 0))
    runs = len(ado.pipeline_runs)
    assert eng.handle(qa(w, "pass", 0)).status == "ignored" and len(ado.pipeline_runs) == runs


def test_dev_blocked_escalates_with_reason():
    ado, eng, _ = make()
    w = bug(ado)
    eng.handle(created(w))
    eng.handle({"eventType": "ai.dev.result", "workItemId": w, "status": "blocked", "summary": "needs a design decision"})
    assert "ai-escalated" in ado.tags(w) and any("design decision" in c for c in ado.comments[w])


def test_token_budget_escalates_and_tokens_accumulate():
    ado, eng, _ = make(token_budget=1000)
    w = bug(ado)
    eng.handle(created(w))
    eng.handle({"eventType": "ai.dev.result", "workItemId": w, "status": "pr_opened", "tokensIn": 400, "tokensOut": 100})
    assert "ai-tokens:500" in ado.tags(w) and "ai-escalated" not in ado.tags(w)
    eng.handle({"eventType": "ai.qa.started", "workItemId": w})
    eng.handle(qa(w, "fail", 1, tokensIn=600))
    assert "ai-escalated" in ado.tags(w) and any("token budget" in c for c in ado.comments[w])


def test_wallclock_sweep_escalates_stuck_items_only():
    ado, eng, clock = make(wallclock_s=3600)
    stuck, fresh = bug(ado), bug(ado)
    eng.handle(created(stuck))
    clock["t"] += 7200
    eng.handle(created(fresh))
    assert eng.sweep() == [stuck]
    assert "ai-escalated" in ado.tags(stuck) and "ai-escalated" not in ado.tags(fresh)


def test_unknown_event_is_ignored():
    ado, eng, _ = make()
    assert eng.handle({"eventType": "git.push"}).status == "ignored"
