from routing import ItemView, on_qa_verdict, on_triage_result, on_work_item_event


def item(tags, bugs=0, state="Active"):
    return ItemView(id=1, type="Bug", state=state, tags=tags, open_child_bugs=bugs)


def test_new_item_goes_to_triage():
    assert on_work_item_event(item(["ai-loop"], state="New"), created=True, changed_by_agent=False).action == "triage"


def test_item_without_loop_tag_ignored():
    assert on_work_item_event(item([]), created=True, changed_by_agent=False).action == "ignore"


def test_ready_item_goes_to_dev():
    d = on_triage_result(item(["ai-loop"]), ready=True, route="dev")
    assert d.action == "queue_dev" and "ai-iter:1" in d.tags_add


def test_pass_goes_to_signoff():
    assert on_qa_verdict(item(["ai-loop", "ai-iter:2"]), "pass", 0, cap=3).action == "ready_for_signoff"


def test_fail_under_cap_loops():
    assert on_qa_verdict(item(["ai-loop", "ai-iter:1"]), "fail", 2, cap=3).action == "queue_dev"


def test_fail_at_cap_escalates():
    assert on_qa_verdict(item(["ai-loop", "ai-iter:3"]), "fail", 1, cap=3).action == "escalate"
