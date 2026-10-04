"""Project adapter: how the generic loop builds, tests and protects ONE target project (see projects/ and docs/15)."""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

from tools import DEFAULT_PROTECTED


@dataclass
class Adapter:
    name: str
    install: str = ""
    build: str = ""
    unit_test: str = ""
    e2e_test: str = ""
    serve: str = ""
    base_url: str = ""
    qa_write_dir: str = "tests/ai-generated/"
    allowed_cmds: tuple[str, ...] = ("git status", "git diff")
    protected: tuple[str, ...] = DEFAULT_PROTECTED
    max_files: int = 15
    max_lines: int = 600
    instructions_file: str = ""
    definition_of_done: tuple[str, ...] = field(default_factory=tuple)

    @staticmethod
    def load(path: str | pathlib.Path) -> "Adapter":
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        budget = d.get("diff_budget", {})
        prot = tuple(dict.fromkeys(tuple(d.get("protected_paths", [])) + DEFAULT_PROTECTED))  # the defaults always apply
        return Adapter(
            name=d["name"], install=d.get("install", ""), build=d.get("build", ""), unit_test=d.get("unit_test", ""),
            e2e_test=d.get("e2e_test", ""), serve=d.get("serve", ""), base_url=d.get("base_url", ""),
            qa_write_dir=d.get("qa_write_dir", "tests/ai-generated/"),
            allowed_cmds=tuple(d.get("allowed_cmds", ("git status", "git diff"))), protected=prot,
            max_files=int(budget.get("files", 15)), max_lines=int(budget.get("lines", 600)),
            instructions_file=d.get("agent_instructions", ""), definition_of_done=tuple(d.get("definition_of_done", ())))
