"""The whole loop (triage -> dev -> trusted gates -> QA -> verdict -> engine) on a real temporary git repo with scripted agents."""
import json
import subprocess
import sys

import pytest

from adapter import Adapter
from llm import Reply, ScriptedProvider, ToolCall
from local_loop import LocalLoop


def tc(name, **args):
    return Reply(tool_calls=[ToolCall(f"c{abs(hash(json.dumps(args, sort_keys=True)))%10**6}", name, args)], tokens_in=100, tokens_out=10)


READY = Reply(text='{"ready": true, "route": "dev", "risk": "low", "comment": "ok"}')
PASS = Reply(text='{"verdict": "pass", "bugs": [], "summary": "all criteria verified"}')


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "proj"
    (r / ".agent").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (r / "tests" / "test_existing.py").write_text("def test_nothing():\n    assert True\n")
    (r / ".agent" / "project.json").write_text(json.dumps({
        "name": "calc", "build": f"{sys.executable} -c 'import calc'", "unit_test": f"{sys.executable} -m pytest -q tests",
        "e2e_test": "", "allowed_cmds": [f"{sys.executable}"], "diff_budget": {"files": 10, "lines": 200}}))
    (r / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.agent-runs/\n")
    for c in (["git", "init", "-q", "-b", "main"], ["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"],
              ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(c, cwd=r, check=True, capture_output=True)
    return r


def factory(dev, qa, tri=None):
    prov = {"triage": ScriptedProvider(tri or [READY]), "dev": ScriptedProvider(dev), "qa": ScriptedProvider(qa)}
    return lambda role: prov[role], prov


TEST_ADD = "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def test_fix_needs_two_iterations_then_ready_for_signoff(repo):
    dev = [
        # iteration 1: writes the reproducing test but "fixes" the code wrongly
        tc("write_file", path="tests/test_add.py", content=TEST_ADD), tc("edit_file", path="calc.py", old="a - b", new="a * b"),
        Reply(text='{"status": "pr_opened", "summary": "first attempt"}'),
        # iteration 2: sees the child bug and fixes it properly
        tc("edit_file", path="calc.py", old="a * b", new="a + b"), Reply(text='{"status": "pr_updated", "summary": "fixed"}'),
    ]
    qa = [PASS, PASS]            # the QA agent is optimistic both times; the trusted gate is what fails iteration 1
    llm_for, prov = factory(dev, qa)
    loop = LocalLoop(repo, Adapter.load(repo / ".agent" / "project.json"), llm_for, cap=3, out_dir=repo / "out")
    rep = loop.run("add(2, 3) returns -1; expected 5", "bug")
    assert rep["status"] == "ready_for_signoff"
    assert [i["qa"] for i in rep["iterations"]] == ["fail", "pass"]
    assert rep["iterations"][0]["gates"]["unit"] is False and rep["iterations"][1]["gates"]["unit"] is True
    assert any("unit gate failed" in b for b in rep["iterations"][0]["new_bugs"])
    # the agent's work is on a branch; the main checkout is untouched and the worktree is gone
    assert "a - b" in (repo / "calc.py").read_text()
    branches = subprocess.run(["git", "branch", "--list", "ai/*"], cwd=repo, capture_output=True, text=True).stdout
    assert rep["branch"] in branches
    assert subprocess.run(["git", "show", f"{rep['branch']}:calc.py"], cwd=repo, capture_output=True, text=True).stdout.count("a + b") == 1
    assert (repo / "out" / "report.md").exists() and (repo / "out" / "dev-it1.jsonl").exists()
    assert not list(repo.parent.glob(".agent-work-*"))
    # iteration 2 context carried the open child bug from iteration 1
    assert "unit gate failed" in prov["dev"].calls[-1]["messages"][0]["content"]


def test_cap_reached_escalates_instead_of_looping(repo):
    wrong = [tc("edit_file", path="calc.py", old="a - b", new="a * b"), tc("write_file", path="tests/test_add.py", content=TEST_ADD), Reply(text='{"status": "pr_opened", "summary": "x"}')]
    again = [tc("edit_file", path="calc.py", old="a * b", new="a / b"), Reply(text='{"status": "pr_updated", "summary": "y"}')]
    llm_for, _ = factory(wrong + again, [PASS, PASS])
    rep = LocalLoop(repo, Adapter.load(repo / ".agent" / "project.json"), llm_for, cap=2, out_dir=repo / "out").run("add is wrong", "bug")
    assert rep["status"] == "escalated" and len(rep["iterations"]) == 2 and "ai-escalated" in rep["tags"]


def test_protected_path_violation_is_a_defect_even_if_agent_claims_success(repo):
    (repo / "pipelines").mkdir()
    (repo / "pipelines" / "ci.yml").write_text("a: 1\n")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "ci"], cwd=repo, check=True)
    # the dev agent tries to edit the pipeline (denied by the sandbox) and then says it is done
    dev = [tc("write_file", path="pipelines/ci.yml", content="evil: true"), tc("edit_file", path="calc.py", old="a - b", new="a + b"),
           tc("write_file", path="tests/test_add.py", content=TEST_ADD), Reply(text='{"status": "pr_opened", "summary": "done"}')]
    llm_for, prov = factory(dev, [PASS])
    rep = LocalLoop(repo, Adapter.load(repo / ".agent" / "project.json"), llm_for, cap=1, out_dir=repo / "out").run("fix add", "bug")
    shown = subprocess.run(["git", "show", f"{rep['branch']}:pipelines/ci.yml"], cwd=repo, capture_output=True, text=True).stdout
    assert shown == "a: 1\n"                                         # sandbox kept the file intact
    assert rep["status"] == "ready_for_signoff"                      # denied writes are not a violation; nothing protected changed
    assert any(t.get("result", "").startswith("DENIED") for t in map(json.loads, (repo / "out" / "dev-it1.jsonl").read_text().splitlines()) if "result" in t)


def test_weakened_tests_are_caught_by_the_diff_policy(repo):
    dev = [tc("write_file", path="tests/test_existing.py", content="def test_nothing():\n    pass\n"),
           tc("write_file", path="tests/test_many.py", content="def test_a():\n    assert True\n" * 3),
           Reply(text='{"status": "pr_opened", "summary": "x"}')]
    # shrink an existing 12-line test file to trigger test-weakened
    (repo / "tests" / "test_existing.py").write_text("".join(f"def test_{i}():\n    assert True\n\n" for i in range(8)))
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "more tests"], cwd=repo, check=True)
    llm_for, _ = factory(dev, [PASS])
    rep = LocalLoop(repo, Adapter.load(repo / ".agent" / "project.json"), llm_for, cap=1, out_dir=repo / "out").run("tidy tests", "bug")
    assert any("test-weakened" in p for p in rep["iterations"][0]["policy"]) and rep["status"] == "escalated"


def test_blocked_dev_agent_escalates_immediately(repo):
    llm_for, _ = factory([Reply(text='{"status": "blocked", "summary": "needs a product decision"}')], [])
    rep = LocalLoop(repo, Adapter.load(repo / ".agent" / "project.json"), llm_for, out_dir=repo / "out").run("big redesign", "story")
    assert rep["status"] == "escalated" and "product decision" in rep["note"] and len(rep["iterations"]) == 1


def test_not_ready_item_stops_at_triage_with_needs_info(repo):
    tri = [Reply(text='{"ready": false, "route": "needs_info", "risk": "low", "comment": "Please add steps to reproduce."}')]
    llm_for, prov = factory([], [], tri)
    rep = LocalLoop(repo, Adapter.load(repo / ".agent" / "project.json"), llm_for, out_dir=repo / "out").run("it is broken", "bug")
    assert rep["status"] == "needs_info" and not rep["iterations"] and not prov["dev"].calls
