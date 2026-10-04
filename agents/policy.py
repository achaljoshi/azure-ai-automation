"""Diff policy for agent-authored changes. Used by the local loop and by pipelines/templates/agent-pr-policy.yml,
so the CI gate and the local gate are the same code (and are unit tested)."""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

from tools import DEFAULT_PROTECTED

SKIP_PATTERNS = re.compile(r"^\+.*(\.skip\(|\bxit\(|\bxdescribe\(|@Disabled|@pytest\.mark\.(skip|xfail)|\[Ignore\]|test\.fixme\(|\bit\.todo\()")


@dataclass
class Violation:
    rule: str
    detail: str


def parse_numstat(numstat: str) -> list[tuple[int, int, str]]:
    out = []
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            a = int(parts[0]) if parts[0].isdigit() else 0
            d = int(parts[1]) if parts[1].isdigit() else 0
            out.append((a, d, parts[2]))
    return out


def _protected(path: str, protected: tuple[str, ...]) -> bool:
    for pat in protected:
        if pat.endswith("/") and (path + "/").startswith(pat):
            return True
        if path == pat or fnmatch.fnmatch(path, pat):
            return True
    return False


def check_diff(numstat: str, diff_text: str, *, protected: tuple[str, ...] = DEFAULT_PROTECTED, max_files: int = 15,
               max_lines: int = 600, role: str = "dev", qa_write_dir: str = "tests/ai-generated/") -> list[Violation]:
    files = parse_numstat(numstat)
    v: list[Violation] = []
    for _, _, path in files:
        if _protected(path, protected):
            v.append(Violation("protected-path", path))
        if role == "qa" and not path.startswith(qa_write_dir):
            v.append(Violation("qa-write-scope", path))
    if len(files) > max_files:
        v.append(Violation("diff-budget", f"{len(files)} files > {max_files}"))
    lines = sum(a + d for a, d, _ in files)
    if lines > max_lines:
        v.append(Violation("diff-budget", f"{lines} changed lines > {max_lines}"))
    for line in diff_text.splitlines():
        if SKIP_PATTERNS.match(line):
            v.append(Violation("skipped-test", line[:120]))
    # deleting tests = weakening them: more than 0 net removed test files or heavy deletions inside test paths
    for a, d, path in files:
        if re.search(r"(^|/)(tests?|__tests__|spec)(/|\.)|\.(test|spec)\.", path) and d > a and d >= 5 and role == "dev":
            v.append(Violation("test-weakened", f"{path}: +{a}/-{d}"))
    return v
