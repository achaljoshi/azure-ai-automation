"""Sandboxed tool layer for the Development and QA agents. Every rule here is enforced in code, not in the prompt.

* Paths are normalised and resolved (no ../, no symlink escape) before any check.
* Protected paths are matched on the normalised relative path (so ./pipelines/x or a/../pipelines/x cannot sneak by).
* The QA agent can write only under `qa_write_dir`; neither role can touch protected paths.
* Commands are parsed with shlex and run WITHOUT a shell; shell metacharacters are rejected; the command must start with an
  allow-listed token sequence; the environment is stripped of secrets.
"""
from __future__ import annotations

import fnmatch
import os
import pathlib
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Any

DEFAULT_PROTECTED = (
    "pipelines/", "infra/", ".azuredevops/", ".github/", ".git/", ".agent/", "azure-pipelines*.yml",
    "qa-thresholds.json", "tests/quarantine.txt",
    "package.json", "package-lock.json", "requirements*.txt", "pyproject.toml",   # dependency changes are a human decision
)
SECRET_ENV = re.compile(r"(TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL|CONNECTION_STRING)", re.I)
META = re.compile(r"[;&|`<>\n\r]|\$\(|\$\{")
MAX_READ = 40_000
MAX_OUT = 12_000

TOOL_SPECS = [
    {"name": "read_file", "description": "Read a UTF-8 text file in the workspace.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "list_dir", "description": "List a directory (directories end with /).", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Create or overwrite a file.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace one exact occurrence of old with new in a file (fails if old is missing or ambiguous).", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}}, "required": ["path", "old", "new"]}},
    {"name": "run", "description": "Run an allow-listed command (no shell). Returns exit code and the tail of the output.", "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}},
]


@dataclass
class Workspace:
    root: pathlib.Path
    role: str                                   # "dev" | "qa"
    allowed_cmds: tuple[str, ...] = ()
    protected: tuple[str, ...] = DEFAULT_PROTECTED
    qa_write_dir: str = "tests/ai-generated/"
    timeout_s: int = 900
    extra_env: dict[str, str] = field(default_factory=dict)
    written: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.root = pathlib.Path(self.root).resolve()

    # ---- path handling -------------------------------------------------------------------------------
    def rel(self, path: str) -> str:
        """Normalised workspace-relative posix path; raises PermissionError if it escapes the workspace."""
        p = (self.root / path.replace("\\", "/")).resolve()
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            raise PermissionError("path outside workspace") from None

    def is_protected(self, rel: str) -> bool:
        r = rel  # already normalised by rel(): no ./ prefix, no .., resolved symlinks
        for pat in self.protected:
            if pat.endswith("/") and (r + "/").startswith(pat):
                return True
            if r == pat or fnmatch.fnmatch(r, pat):
                return True
        return False

    def _check_write(self, rel: str) -> str | None:
        if rel in ("", "."):
            return "DENIED: not a file path"
        if self.is_protected(rel):
            return "DENIED: protected path"
        if self.role == "qa" and not (rel + "").startswith(self.qa_write_dir):
            return f"DENIED: QA agent may only write under {self.qa_write_dir}"
        return None

    # ---- tools ---------------------------------------------------------------------------------------
    def read_file(self, path: str) -> str:
        p = self.root / self.rel(path)
        if p.is_dir():
            return "ERROR: is a directory"
        data = p.read_bytes()
        if b"\0" in data[:4096]:
            return "ERROR: binary file"
        return data.decode("utf-8", errors="replace")[:MAX_READ]

    def list_dir(self, path: str) -> str:
        p = self.root / self.rel(path)
        return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir() if x.name != ".git"))

    def write_file(self, path: str, content: str) -> str:
        rel = self.rel(path)
        if (denied := self._check_write(rel)):
            return denied
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self.written.add(rel)
        return "written"

    def edit_file(self, path: str, old: str, new: str) -> str:
        rel = self.rel(path)
        if (denied := self._check_write(rel)):
            return denied
        p = self.root / rel
        text = p.read_text(encoding="utf-8")
        n = text.count(old)
        if n == 0:
            return "ERROR: old text not found"
        if n > 1:
            return f"ERROR: old text occurs {n} times; include more context"
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
        self.written.add(rel)
        return "edited"

    def command_allowed(self, cmd: str) -> tuple[list[str] | None, str]:
        if META.search(cmd):
            return None, "DENIED: shell metacharacters are not allowed"
        try:
            argv = shlex.split(cmd)
        except ValueError as e:
            return None, f"DENIED: cannot parse command ({e})"
        if not argv:
            return None, "DENIED: empty command"
        for allowed in self.allowed_cmds:
            toks = allowed.split()
            if argv[:len(toks)] == toks:
                return argv, ""
        return None, f"DENIED: command not allow-listed ({', '.join(self.allowed_cmds)})"

    def run(self, cmd: str) -> str:
        argv, err = self.command_allowed(cmd.strip())
        if argv is None:
            return err
        env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
        env.update(self.extra_env)
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout_s, env=env, cwd=self.root)
        except FileNotFoundError:
            return f"ERROR: command not found: {argv[0]}"
        except subprocess.TimeoutExpired:
            return f"ERROR: timed out after {self.timeout_s}s"
        return f"exit={r.returncode}\n{(r.stdout + r.stderr)[-MAX_OUT:]}"

    def call(self, name: str, args: dict[str, Any]) -> str:
        try:
            if name == "read_file":
                return self.read_file(args["path"])
            if name == "list_dir":
                return self.list_dir(args["path"])
            if name == "write_file":
                return self.write_file(args["path"], args["content"])
            if name == "edit_file":
                return self.edit_file(args["path"], args["old"], args["new"])
            if name == "run":
                return self.run(args["cmd"])
        except PermissionError as e:
            return f"DENIED: {e}"
        except Exception as e:  # noqa: BLE001 - surface errors to the model, never crash the loop
            return f"ERROR: {e}"
        return "ERROR: unknown tool"
