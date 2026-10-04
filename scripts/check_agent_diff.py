"""CI gate for agent pull requests (branches ai/*): protected paths, diff budget, skipped or deleted tests.

    python scripts/check_agent_diff.py --base origin/main [--project .agent/project.json]
Same code as the local loop's gate (agents/policy.py), so a PR that passes locally passes here.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

from adapter import Adapter  # noqa: E402
from policy import check_diff  # noqa: E402
from tools import DEFAULT_PROTECTED  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--project", default=".agent/project.json")
    ap.add_argument("--role", choices=["dev", "qa"], default="dev")
    a = ap.parse_args()
    ad = Adapter.load(a.project) if os.path.exists(a.project) else None
    numstat = subprocess.run(["git", "diff", "--numstat", f"{a.base}...HEAD"], capture_output=True, text=True, check=True).stdout
    diff = subprocess.run(["git", "diff", f"{a.base}...HEAD"], capture_output=True, text=True, check=True).stdout
    viol = check_diff(numstat, diff, protected=ad.protected if ad else DEFAULT_PROTECTED, max_files=ad.max_files if ad else 15,
                      max_lines=ad.max_lines if ad else 600, role=a.role, qa_write_dir=ad.qa_write_dir if ad else "tests/ai-generated/")
    for v in viol:
        print(f"##vso[task.logissue type=error]{v.rule}: {v.detail}")
    print("agent PR policy:", "FAILED" if viol else "ok")
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(main())
