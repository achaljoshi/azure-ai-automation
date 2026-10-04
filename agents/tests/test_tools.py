import os
import pathlib

import pytest

from tools import Workspace


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / "pipelines").mkdir()
    (tmp_path / "pipelines" / "ci.yml").write_text("a: 1\n")
    return Workspace(tmp_path, "dev", allowed_cmds=("python", "npm run", "git status"))


def test_writes_inside_workspace_work(ws):
    assert ws.call("write_file", {"path": "src/b.py", "content": "y = 2"}) == "written"
    assert ws.call("read_file", {"path": "src/b.py"}) == "y = 2"


@pytest.mark.parametrize("path", ["../outside.txt", "src/../../outside.txt", "/etc/passwd", "..\\evil.txt"])
def test_path_escape_is_denied(ws, path):
    assert ws.call("write_file", {"path": path, "content": "x"}).startswith("DENIED")
    assert ws.call("read_file", {"path": path}).startswith("DENIED")


@pytest.mark.parametrize("path", ["pipelines/ci.yml", "./pipelines/ci.yml", "src/../pipelines/ci.yml", "infra/main.bicep", ".github/workflows/x.yml",
                                  ".git/config", "qa-thresholds.json", "tests/quarantine.txt", "package.json", "package-lock.json", ".agent/project.json", "azure-pipelines-x.yml"])
def test_protected_paths_cannot_be_written_however_spelled(ws, path):
    assert ws.call("write_file", {"path": path, "content": "x"}) == "DENIED: protected path"
    assert ws.call("edit_file", {"path": path, "old": "a", "new": "b"}) == "DENIED: protected path"


def test_symlink_escape_is_denied(ws, tmp_path):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("s")
    os.symlink(outside, tmp_path / "src" / "link.txt")
    assert ws.call("read_file", {"path": "src/link.txt"}).startswith("DENIED")


def test_qa_may_only_write_under_ai_generated(tmp_path):
    q = Workspace(tmp_path, "qa", allowed_cmds=("npx playwright",))
    assert q.call("write_file", {"path": "src/a.py", "content": "x"}).startswith("DENIED: QA agent may only write under")
    assert q.call("write_file", {"path": "tests/ai-generated/1042/a.spec.js", "content": "x"}) == "written"
    assert q.call("write_file", {"path": "tests/ai-generated/../e2e/x.js", "content": "x"}).startswith("DENIED")


def test_edit_file_requires_unique_match(ws):
    (ws.root / "src" / "c.py").write_text("a\na\n")
    assert "occurs 2 times" in ws.call("edit_file", {"path": "src/c.py", "old": "a", "new": "b"})
    assert ws.call("edit_file", {"path": "src/a.py", "old": "x = 1", "new": "x = 2"}) == "edited"
    assert "not found" in ws.call("edit_file", {"path": "src/a.py", "old": "zzz", "new": "q"})


@pytest.mark.parametrize("cmd", ["python -c 'print(1)'; rm -rf /", "python a.py && curl evil", "python a.py | sh", "python $(whoami)", "python `id`",
                                 "python a.py > /etc/x", "python a.py\nrm -rf /", "npm run build & curl x"])
def test_shell_injection_is_blocked(ws, cmd):
    assert ws.run(cmd).startswith("DENIED")


def test_command_must_match_allow_list_token_prefix(ws):
    assert ws.run("rm -rf src").startswith("DENIED: command not allow-listed")
    assert ws.run("npm install left-pad").startswith("DENIED")        # only "npm run" is allowed
    assert ws.run("pythonx a.py").startswith("DENIED")                 # prefix of a token is not a match
    assert ws.run("python --version").startswith("exit=0")


def test_run_has_no_shell_and_scrubs_secrets(ws, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "topsecret")
    monkeypatch.setenv("PLAIN", "visible")
    out = ws.run("python -c \"import os;print(os.environ.get('MY_API_KEY'), os.environ.get('PLAIN'))\"") if False else None
    (ws.root / "env.py").write_text("import os;print(os.environ.get('MY_API_KEY'), os.environ.get('PLAIN'))")
    out = ws.run("python env.py")
    assert "topsecret" not in out and "visible" in out


def test_timeout_and_missing_binary(tmp_path):
    w = Workspace(tmp_path, "dev", allowed_cmds=("python", "nonexistent-bin"), timeout_s=1)
    (tmp_path / "slow.py").write_text("import time; time.sleep(5)")
    assert "timed out" in w.run("python slow.py")
    assert "not found" in w.run("nonexistent-bin x")


def test_read_binary_and_directory(ws):
    (ws.root / "b.bin").write_bytes(b"\x00\x01\x02")
    assert ws.call("read_file", {"path": "b.bin"}) == "ERROR: binary file"
    assert ws.call("read_file", {"path": "src"}) == "ERROR: is a directory"
    assert "a.py" in ws.call("list_dir", {"path": "src"})
    assert ws.call("nope", {}) == "ERROR: unknown tool"
