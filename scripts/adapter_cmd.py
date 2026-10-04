"""Print one command from the project adapter so pipeline YAML stays project-agnostic:  eval "$(python adapter_cmd.py build)" """
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))

from adapter import Adapter  # noqa: E402

KEYS = ("install", "build", "unit_test", "e2e_test", "serve", "base_url", "qa_write_dir")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("key", choices=KEYS)
    ap.add_argument("--project", default=".agent/project.json")
    a = ap.parse_args()
    value = getattr(Adapter.load(a.project), a.key)
    print(value or "true")        # an unconfigured step is a no-op, not a failure
    return 0


if __name__ == "__main__":
    sys.exit(main())
