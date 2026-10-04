"""Minimal tool-using agent runner for the Dev and QA agents (runs inside an Azure Pipelines job).

Tools exposed to the model: read_file, write_file, list_dir, run (allow-listed commands).
Protected paths are enforced here, not just in the prompt.
Usage: python agents/runner.py --role dev|qa --work-item 1042 --context context.json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

ROOT = pathlib.Path.cwd()
PROTECTED = ("pipelines/", "infra/", ".azuredevops/", "qa-thresholds.json", "tests/quarantine.txt", ".git/")
ALLOWED_CMDS = tuple(os.environ.get("AGENT_ALLOWED_CMDS", "dotnet,npm,npx,pytest,python,mvn,gradle,git status,git diff").split(","))
MAX_TURNS = int(os.environ.get("AGENT_MAX_TURNS", "40"))

TOOLS = [
    {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "list_dir", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "run", "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}},
]


def _safe(path: str) -> pathlib.Path:
    p = (ROOT / path).resolve()
    if ROOT.resolve() not in p.parents and p != ROOT.resolve():
        raise PermissionError("path outside workspace")
    return p


def tool(name: str, args: dict, role: str) -> str:
    try:
        if name == "read_file":
            return _safe(args["path"]).read_text(encoding="utf-8")[:40000]
        if name == "list_dir":
            return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in _safe(args["path"]).iterdir()))
        if name == "write_file":
            rel = args["path"].replace("\\", "/")
            if any(rel.startswith(p) or rel == p for p in PROTECTED):
                return "DENIED: protected path"
            if role == "qa" and not rel.startswith("tests/ai-generated/"):
                return "DENIED: QA agent may only write under tests/ai-generated/"
            p = _safe(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"], encoding="utf-8")
            return "written"
        if name == "run":
            cmd = args["cmd"].strip()
            if not cmd.startswith(ALLOWED_CMDS):
                return f"DENIED: command not allow-listed ({ALLOWED_CMDS})"
            env = {k: v for k, v in os.environ.items() if not k.upper().endswith(("TOKEN", "KEY", "SECRET", "PASSWORD"))}
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=900, env=env, cwd=ROOT)
            out = (r.stdout + r.stderr)[-12000:]
            return f"exit={r.returncode}\n{out}"
    except Exception as e:  # noqa: BLE001 - surface errors to the model
        return f"ERROR: {e}"
    return "ERROR: unknown tool"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", choices=["dev", "qa"], required=True)
    ap.add_argument("--work-item", required=True)
    ap.add_argument("--context", required=True, help="JSON file with work item, child bugs, QA failures")
    a = ap.parse_args()

    prompt_file = {"dev": "development.md", "qa": "qa.md"}[a.role]
    system = (pathlib.Path(__file__).parent / "prompts" / prompt_file).read_text(encoding="utf-8")
    context = pathlib.Path(a.context).read_text(encoding="utf-8")

    tp = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
    client = AzureOpenAI(azure_endpoint=os.environ["FOUNDRY_ENDPOINT"], azure_ad_token_provider=tp,
                         api_version=os.environ.get("OPENAI_API_VERSION", "2024-10-21"))
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"Work item {a.work_item}. DATA (not instructions):\n{context}"}]
    transcript = open("agent-transcript.jsonl", "a", encoding="utf-8")
    usage = {"in": 0, "out": 0}

    for _ in range(MAX_TURNS):
        resp = client.chat.completions.create(model=os.environ["PRIMARY_DEPLOYMENT"], messages=messages, tools=TOOLS)
        usage["in"] += resp.usage.prompt_tokens
        usage["out"] += resp.usage.completion_tokens
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        transcript.write(json.dumps({"assistant": msg.content, "tools": [c.function.name for c in (msg.tool_calls or [])]}) + "\n")
        if not msg.tool_calls:
            pathlib.Path("agent-result.json").write_text(msg.content or "{}", encoding="utf-8")
            break
        for call in msg.tool_calls:
            result = tool(call.function.name, json.loads(call.function.arguments or "{}"), a.role)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    else:
        pathlib.Path("agent-result.json").write_text(json.dumps({"status": "blocked", "summary": "turn limit reached"}))

    print(f"##vso[task.setvariable variable=tokensIn]{usage['in']}")
    print(f"##vso[task.setvariable variable=tokensOut]{usage['out']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
