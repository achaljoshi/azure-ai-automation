import json
import subprocess
import sys

import post_event
import post_qa_results as pq
import build_context
from fake_ado import FakeAdo


def test_file_bugs_creates_children_and_skips_duplicates():
    ado = FakeAdo()
    parent = ado.create("Bug", "Login", ["ai-loop"])
    res = {"bugs": [{"title": "Cookie lost", "severity": 2, "steps": ["a<b>", "c"], "expected": "kept", "actual": "lost", "evidence": ["trace.zip"], "test": "t1", "signature": "s1"},
                    {"title": "[AI-QA] Cookie lost", "severity": 2}, {"title": "Typo", "severity": "x"}]}
    n = pq.file_bugs(ado, parent, res, existing_titles=set())
    assert n == 2
    kids = [i for i in ado.items.values() if i["id"] != parent]
    assert {k["fields"]["System.Title"] for k in kids} == {"[AI-QA] Cookie lost", "[AI-QA] Typo"}
    cookie = next(k for k in kids if "Cookie" in k["fields"]["System.Title"])
    assert "&lt;b&gt;" in cookie["fields"]["Microsoft.VSTS.TCM.ReproSteps"]            # html-escaped
    assert cookie["fields"]["Microsoft.VSTS.Common.Severity"] == "2 - High" and "ai-raised" in cookie["fields"]["System.Tags"]
    assert pq.file_bugs(ado, parent, res, existing_titles={"[AI-QA] Cookie lost", "[AI-QA] Typo"}) == 0


def test_event_payloads():
    ev = pq.build_event(5, {"verdict": "fail", "bugs": [{"signature": "b"}, {"signature": "a"}]}, 2, 10, 5)
    assert ev["eventType"] == "ai.qa.verdict" and ev["newBugs"] == 2 and ev["tokensIn"] == 10
    assert ev["failSignature"] == pq.fail_signature([{"signature": "a"}, {"signature": "b"}])          # order-independent
    assert pq.fail_signature([]) == ""
    d = post_event.build("ai.dev.result", 7, {"status": "pr_opened", "summary": "x", "pr_url": "http://pr"}, 1, 2)
    assert d["status"] == "pr_opened" and d["prUrl"] == "http://pr"
    assert post_event.build("ai.qa.started", 7, None, 0, 0) == {"eventType": "ai.qa.started", "workItemId": 7, "tokensIn": 0, "tokensOut": 0}


def test_build_context_includes_open_child_bugs_only():
    ado = FakeAdo()
    p = ado.create("Bug", "Parent", ["ai-loop"], **{"System.Description": "d"})
    open_child = ado.create_child_bug(p, "child open", "<p>repro</p>", "2 - High", [])
    done = ado.create_child_bug(p, "child done", "", "3 - Medium", [])
    ado.set_state(done, "Closed")
    ctx = build_context.build(ado, p, "2", {"test_base_url": "http://x"})
    assert [c["id"] for c in ctx["open_child_bugs"]] == [open_child] and ctx["iteration"] == "2" and ctx["test_base_url"] == "http://x"
    assert ctx["work_item"]["System.Title"] == "Parent"


def git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True)


def run_gate(cwd, *extra):
    return subprocess.run([sys.executable, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "scripts" / "check_agent_diff.py"), "--base", "main", *extra], cwd=cwd, capture_output=True, text=True)


def test_check_agent_diff_cli_blocks_protected_and_budget(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("1")
    git(tmp_path, "add", "-A"); git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-q", "-b", "ai/1")
    (tmp_path / "a.txt").write_text("2")
    git(tmp_path, "add", "-A"); git(tmp_path, "commit", "-qm", "ok")
    assert run_gate(tmp_path).returncode == 0
    (tmp_path / "pipelines").mkdir(); (tmp_path / "pipelines" / "ci.yml").write_text("x")
    git(tmp_path, "add", "-A"); git(tmp_path, "commit", "-qm", "bad")
    r = run_gate(tmp_path)
    assert r.returncode == 1 and "protected-path" in r.stdout
