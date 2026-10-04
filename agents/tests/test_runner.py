import json

import pytest

from llm import Reply, ScriptedProvider, ToolCall
from runner import run_agent, validate_result
from tools import Workspace


def tc(name, **args):
    return Reply(tool_calls=[ToolCall(f"id{abs(hash(json.dumps(args, sort_keys=True))) % 10**6}", name, args)], tokens_in=100, tokens_out=20)


def test_dev_agent_edits_runs_tests_and_returns_validated_json(tmp_path):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    ws = Workspace(tmp_path, "dev", allowed_cmds=("python",))
    llm = ScriptedProvider([
        tc("read_file", path="calc.py"),
        tc("edit_file", path="calc.py", old="a - b", new="a + b"),
        tc("run", cmd="python -c 'import calc'"),                   # python -c with quotes is fine (no metacharacters)
        Reply(text='```json\n{"status": "pr_opened", "summary": "fixed add"}\n```', tokens_in=50, tokens_out=10),
    ])
    run = run_agent("dev", "SYS", "task", ws, llm)
    assert run.result == {"status": "pr_opened", "summary": "fixed add"}
    assert "a + b" in (tmp_path / "calc.py").read_text()
    assert (run.turns, run.tool_calls, run.tokens_in, run.tokens_out, run.denied) == (4, 3, 350, 70, 0)
    assert llm.calls[1]["messages"][-1]["role"] == "tool"          # the tool result is fed back to the model


def test_denied_actions_are_counted_and_do_not_stop_the_agent(tmp_path):
    ws = Workspace(tmp_path, "dev", allowed_cmds=("python",))
    llm = ScriptedProvider([tc("write_file", path="pipelines/ci.yml", content="x"), tc("run", cmd="rm -rf /"), Reply(text='{"status": "blocked", "summary": "cannot"}')])
    run = run_agent("dev", "SYS", "t", ws, llm)
    assert run.denied == 2 and run.result["status"] == "blocked" and not (tmp_path / "pipelines").exists()


def test_invalid_dev_output_fails_safe_to_blocked(tmp_path):
    ws = Workspace(tmp_path, "dev")
    assert run_agent("dev", "S", "t", ws, ScriptedProvider([Reply(text="all done!")])).result["status"] == "blocked"
    assert run_agent("dev", "S", "t", ws, ScriptedProvider([Reply(text='{"status": "merged_to_main"}')])).result["status"] == "blocked"


def test_turn_limit_blocks_instead_of_looping_forever(tmp_path):
    ws = Workspace(tmp_path, "dev")
    llm = ScriptedProvider([tc("list_dir", path=".")] * 5)
    run = run_agent("dev", "S", "t", ws, llm, max_turns=3)
    assert run.result["status"] == "blocked" and run.turns == 3


def test_qa_pass_with_severity_2_bug_is_downgraded():
    r = validate_result("qa", {"verdict": "pass", "bugs": [{"title": "x", "severity": 2}], "summary": "ok"})
    assert r["verdict"] == "fail" and "downgraded" in r["summary"]
    assert validate_result("qa", {"verdict": "pass", "bugs": [{"severity": 3}]})["verdict"] == "pass"


def test_invalid_qa_output_is_a_fail_never_a_pass():
    r = validate_result("qa", {"verdict": "looks fine"})
    assert r["verdict"] == "fail" and r["invalid"]
    assert validate_result("qa", {})["verdict"] == "fail"


def test_qa_agent_cannot_modify_application_code(tmp_path):
    (tmp_path / "app.py").write_text("x=1")
    ws = Workspace(tmp_path, "qa", allowed_cmds=("python",))
    llm = ScriptedProvider([tc("write_file", path="app.py", content="x=2"), tc("write_file", path="tests/ai-generated/7/t.py", content="assert True"), Reply(text='{"verdict": "pass", "bugs": [], "summary": "ok"}')])
    run = run_agent("qa", "S", "t", ws, llm)
    assert (tmp_path / "app.py").read_text() == "x=1" and (tmp_path / "tests/ai-generated/7/t.py").exists() and run.denied == 1
