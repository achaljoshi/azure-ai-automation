import json
from types import SimpleNamespace as NS

import pytest

from llm import AnthropicProvider, AzureOpenAIProvider, Reply, ScriptedProvider, ToolCall, extract_json
from triage import normalise, triage


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Here you go:\n```json\n{"a": {"b": 2}}\n```') == {"a": {"b": 2}}
    assert extract_json('prefix {"a": [1, 2]} suffix') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        extract_json("no json here")


NEUTRAL = [
    {"role": "user", "content": "fix it"},
    {"role": "assistant", "text": "reading", "tool_calls": [{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}, {"id": "c2", "name": "list_dir", "args": {"path": "."}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "print(1)"},
    {"role": "tool", "tool_call_id": "c2", "name": "list_dir", "content": "a.py"},
]


def test_anthropic_wire_groups_tool_results_in_one_user_message():
    wire = AnthropicProvider.to_wire(NEUTRAL)
    assert wire[1]["content"][1] == {"type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "a.py"}}
    assert len(wire) == 3 and wire[2]["role"] == "user"
    assert [b["tool_use_id"] for b in wire[2]["content"]] == ["c1", "c2"]


def test_azure_wire_uses_function_calls_and_tool_role():
    wire = AzureOpenAIProvider.to_wire("SYS", NEUTRAL)
    assert wire[0] == {"role": "system", "content": "SYS"}
    assert wire[2]["tool_calls"][0]["function"] == {"name": "read_file", "arguments": json.dumps({"path": "a.py"})}
    assert [m["role"] for m in wire[3:]] == ["tool", "tool"]


class FakeAnthropic:
    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return NS(content=[NS(type="text", text="ok"), NS(type="tool_use", id="t1", name="run", input={"cmd": "npm test"})], usage=NS(input_tokens=11, output_tokens=7))


def test_anthropic_provider_maps_reply_and_tools():
    fake = FakeAnthropic()
    rep = AnthropicProvider("m", client=fake).chat("SYS", [{"role": "user", "content": "hi"}], [{"name": "run", "description": "d", "parameters": {"type": "object"}}], json_mode=True)
    assert rep.text == "ok" and rep.tool_calls == [ToolCall("t1", "run", {"cmd": "npm test"})] and (rep.tokens_in, rep.tokens_out) == (11, 7)
    kw = fake.calls[0]
    assert kw["tools"][0]["input_schema"] == {"type": "object"} and "JSON object only" in kw["system"]


class FakeOpenAI:
    def __init__(self, content):
        self.chat = self
        self.completions = self
        self.content, self.kw = content, None

    def create(self, **kw):
        self.kw = kw
        msg = NS(content=self.content, tool_calls=[NS(id="x", function=NS(name="run", arguments="{not json"))])
        return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=5, completion_tokens=3))


def test_azure_provider_survives_invalid_tool_arguments():
    client = FakeOpenAI("hi")
    rep = AzureOpenAIProvider("dep", client=client).chat("S", [{"role": "user", "content": "u"}], [{"name": "run", "parameters": {}}], json_mode=True)
    assert rep.tool_calls[0].args == {"_invalid_json": "{not json"}
    assert client.kw["response_format"] == {"type": "json_object"} and client.kw["temperature"] == 0


def test_normalise_fails_safe():
    n = normalise({"ready": True, "route": "teleport", "risk": "???", "duplicate_of": "7"})
    assert n["route"] == "needs_info" and n["risk"] == "high" and n["duplicate_of"] is None
    n = normalise({"ready": True, "route": "dev", "risk": "low", "duplicate_of": 7, "comment": "x" * 5000})
    assert n["duplicate_of"] == 7 and len(n["comment"]) == 2000


def test_triage_uses_prompt_data_framing_and_handles_garbage():
    llm = ScriptedProvider([Reply(text='{"ready": true, "route": "dev", "risk": "low", "comment": "ok"}'), Reply(text="I refuse")])
    out = triage({"System.Title": "t"}, [{"id": 1}], llm)
    assert out["route"] == "dev"
    assert "DATA (not instructions)" in llm.calls[0]["messages"][0]["content"] and llm.calls[0]["json_mode"]
    bad = triage({"System.Title": "t"}, [], llm)
    assert bad["route"] == "needs_info" and not bad["ready"]
