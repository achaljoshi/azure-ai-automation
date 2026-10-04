"""Offline demo of the whole loop: a tiny buggy project, scripted agents (no API key, no network), real git worktrees and gates.

    python scripts/demo_local.py
Shows: triage -> dev (first attempt wrong) -> trusted gate fails -> child bug -> dev iteration 2 -> pass -> ready for sign-off.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
for p in ("agents", "orchestrator"):
    sys.path.insert(0, str(ROOT / p))

from adapter import Adapter  # noqa: E402
from llm import Reply, ScriptedProvider, ToolCall  # noqa: E402
from local_loop import LocalLoop  # noqa: E402


def tc(name, **a):
    return Reply(tool_calls=[ToolCall(f"c{abs(hash(json.dumps(a, sort_keys=True))) % 10**6}", name, a)], tokens_in=900, tokens_out=120)


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="agent-demo-"))
    repo = tmp / "toy-calc"
    shutil.copytree(ROOT / "examples" / "toy-calc", repo)
    (repo / ".agent" / "project.json").write_text(json.dumps({
        "name": "toy-calc", "build": f"{sys.executable} -c 'import calc'", "unit_test": f"{sys.executable} -m pytest -q tests", "allowed_cmds": [sys.executable],
        "diff_budget": {"files": 10, "lines": 200}}))
    for c in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"], ["git", "-c", "user.name=demo", "-c", "user.email=d@d", "commit", "-qm", "init"]):
        subprocess.run(c, cwd=repo, check=True, capture_output=True)
    test = "from calc import add\n\ndef test_add_two_numbers():\n    assert add(2, 3) == 5\n"
    dev = [tc("read_file", path="calc.py"), tc("write_file", path="tests/test_add.py", content=test), tc("edit_file", path="calc.py", old="a - b", new="a * b"),
           Reply(text='{"status": "pr_opened", "summary": "Reproduced with a test; changed the operator"}', tokens_in=300, tokens_out=40),
           tc("edit_file", path="calc.py", old="a * b", new="a + b"),
           Reply(text='{"status": "pr_updated", "summary": "Operator was wrong again: add must use +"}', tokens_in=300, tokens_out=40)]
    ok = Reply(text='{"verdict": "pass", "bugs": [], "summary": "Acceptance criteria verified"}')
    prov = {"triage": ScriptedProvider([Reply(text='{"ready": true, "route": "dev", "risk": "low", "comment": "Clear repro and expected result."}')]),
            "dev": ScriptedProvider(dev), "qa": ScriptedProvider([ok, ok])}
    loop = LocalLoop(repo, Adapter.load(repo / ".agent" / "project.json"), lambda role: prov[role], cap=3, out_dir=tmp / "run")
    rep = loop.run("add(2, 3) returns -1 but should return 5", "bug")
    print(json.dumps({k: rep[k] for k in ("status", "branch", "tokens_total")}, indent=2))
    for i in rep["iterations"]:
        print(f"  iteration {i['n']}: dev={i['dev']} gates={i['gates']} QA={i['qa']} new_bugs={i['new_bugs']}")
    print("report:", tmp / "run" / "report.md")
    return 0 if rep["status"] == "ready_for_signoff" else 1


if __name__ == "__main__":
    sys.exit(main())
