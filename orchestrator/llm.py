"""Provider-neutral LLM layer: one tool-calling interface over Azure OpenAI, Anthropic (Claude) and a scripted fake.

Neutral message format (what the agent loop keeps):
  {"role": "user", "content": str}
  {"role": "assistant", "text": str | None, "tool_calls": [{"id", "name", "args": dict}]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
Neutral tool format: {"name", "description", "parameters": <JSON schema>}.

Select with LLM_PROVIDER=azure|anthropic (default azure). Credentials come from the environment / managed identity;
nothing is read from files and nothing is logged.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Reply:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


class LLM(Protocol):
    def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False) -> Reply: ...


def extract_json(text: str) -> dict:
    """Parse a JSON object from model output, tolerating code fences and surrounding prose."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return json.loads(fence.group(1))
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            depth += (text[i] == "{") - (text[i] == "}")
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except ValueError:
                    break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object found in model output")


# ------------------------------------------------------------------------------------------------ Azure OpenAI
class AzureOpenAIProvider:
    def __init__(self, deployment: str, client: Any = None):
        self.deployment = deployment
        if client is None:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            from openai import AzureOpenAI
            tp = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
            client = AzureOpenAI(azure_endpoint=os.environ["FOUNDRY_ENDPOINT"], azure_ad_token_provider=tp,
                                 api_version=os.environ.get("OPENAI_API_VERSION", "2024-10-21"))
        self.client = client

    @staticmethod
    def to_wire(system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.get("text")}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}} for c in m["tool_calls"]]
                out.append(msg)
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        return out

    def chat(self, system, messages, tools=None, json_mode=False) -> Reply:
        kw: dict[str, Any] = {"model": self.deployment, "messages": self.to_wire(system, messages)}
        if tools:
            kw["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["parameters"]}} for t in tools]
        if json_mode:
            kw["response_format"] = {"type": "json_object"}
            kw["temperature"] = 0
        resp = self.client.chat.completions.create(**kw)
        msg = resp.choices[0].message
        calls = []
        for c in (msg.tool_calls or []):
            try:
                args = json.loads(c.function.arguments or "{}")
            except ValueError:
                args = {"_invalid_json": c.function.arguments}
            calls.append(ToolCall(c.id, c.function.name, args))
        u = getattr(resp, "usage", None)
        return Reply(msg.content, calls, getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0)


# ------------------------------------------------------------------------------------------------ Anthropic
class AnthropicProvider:
    def __init__(self, model: str | None = None, client: Any = None, max_tokens: int = 8192):
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.max_tokens = max_tokens
        if client is None:
            import anthropic
            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.client = client

    @staticmethod
    def to_wire(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                blocks: list[dict] = []
                if m.get("text"):
                    blocks.append({"type": "text", "text": m["text"]})
                for c in m.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]})
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)  # all results of one assistant turn go in one user message
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    def chat(self, system, messages, tools=None, json_mode=False) -> Reply:
        kw: dict[str, Any] = {"model": self.model, "max_tokens": self.max_tokens, "system": system, "messages": self.to_wire(messages)}
        if json_mode:
            kw["system"] = system + "\n\nRespond with a single JSON object only, no prose."
        if tools:
            kw["tools"] = [{"name": t["name"], "description": t.get("description", ""), "input_schema": t["parameters"]} for t in tools]
        resp = self.client.messages.create(**kw)
        text, calls = [], []
        for b in resp.content:
            if b.type == "text":
                text.append(b.text)
            elif b.type == "tool_use":
                calls.append(ToolCall(b.id, b.name, dict(b.input)))
        u = getattr(resp, "usage", None)
        return Reply("".join(text) or None, calls, getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0)


# ------------------------------------------------------------------------------------------------ scripted (tests, simulator)
class ScriptedProvider:
    """Plays back a list of replies (or callables `(system, messages, tools) -> Reply`). Records every call."""

    def __init__(self, script: list[Reply | Callable[..., Reply]]):
        self.script, self.calls = list(script), []

    def chat(self, system, messages, tools=None, json_mode=False) -> Reply:
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools, "json_mode": json_mode})
        if not self.script:
            raise RuntimeError("ScriptedProvider ran out of replies")
        step = self.script.pop(0)
        return step(system, messages, tools) if callable(step) else step


def make_provider(role: str = "primary") -> LLM:
    """role: "triage" uses the small/cheap model; anything else ("primary", "dev", "qa") the coding model."""
    kind = os.environ.get("LLM_PROVIDER", "azure").lower()
    if kind == "anthropic":
        return AnthropicProvider(os.environ.get("ANTHROPIC_TRIAGE_MODEL") if role == "triage" else None)
    if kind == "azure":
        dep = os.environ["TRIAGE_DEPLOYMENT"] if role == "triage" else os.environ["PRIMARY_DEPLOYMENT"]
        return AzureOpenAIProvider(dep)
    raise ValueError(f"unknown LLM_PROVIDER {kind!r} (use azure or anthropic)")
