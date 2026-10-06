"""Structural checks on the pipeline YAML: parses, has the keys Azure Pipelines requires, and every script/template it references exists."""
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "pipelines").glob("*.yml")) + sorted((ROOT / "pipelines" / "templates").glob("*.yml"))


def steps_of(doc):
    if "steps" in doc:
        yield from doc["steps"]
    for j in doc.get("jobs", []):
        yield from j.get("steps", [])
        for k in ("strategy",):
            run = (j.get(k) or {}).get("runOnce", {}).get("deploy", {}).get("steps", [])
            yield from run
    for st in doc.get("stages", []):
        for j in st.get("jobs", []):
            yield from j.get("steps", [])
            yield from ((j.get("strategy") or {}).get("runOnce", {}).get("deploy", {}).get("steps", []))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_yaml_parses_and_has_steps(path):
    doc = yaml.safe_load(path.read_text())
    assert isinstance(doc, (dict, list))
    if path.parent.name == "pipelines":
        assert list(steps_of(doc)), f"{path.name} has no steps"
    else:
        assert "steps" in doc


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_referenced_scripts_and_templates_exist(path):
    text = path.read_text()
    for m in re.finditer(r'(?:KIT\)?/|\.\./|\bpython )"?\$?\(?[A-Za-z_]*\)?/?((?:scripts|agents)/[A-Za-z_]+\.py)', text):
        assert (ROOT / m.group(1)).exists(), f"{path.name} references missing {m.group(1)}"
    for m in re.finditer(r"template: (templates/[\w\-]+\.yml)", text):
        assert (ROOT / "pipelines" / m.group(1)).exists(), f"{path.name} references missing template {m.group(1)}"


def test_agent_pipelines_use_kit_resource_and_trusted_gates():
    dev = yaml.safe_load((ROOT / "pipelines" / "dev-agent.yml").read_text())
    assert dev["resources"]["repositories"][0]["repository"] == "agentkit"
    text = (ROOT / "pipelines" / "dev-agent.yml").read_text()
    assert text.count("templates/build-and-unit-test.yml") == 2          # before AND after the agent: never trust its claim
    assert "check_agent_diff.py" in text and "ai.dev.result" in text
    qa = (ROOT / "pipelines" / "qa-agent.yml").read_text()
    assert "post_qa_results.py" in qa and "adapter_cmd.py\" e2e_test" in qa


def test_deploy_notifies_orchestrator_before_queueing_qa():
    t = (ROOT / "pipelines" / "deploy-test.yml").read_text()
    assert t.index("ai.qa.started") < t.index("az pipelines run")


def test_every_parameter_used_is_declared():
    for f in ("dev-agent.yml", "qa-agent.yml"):
        doc = yaml.safe_load((ROOT / "pipelines" / f).read_text())
        declared = {p["name"] for p in doc["parameters"]}
        used = set(re.findall(r"parameters\.(\w+)", (ROOT / "pipelines" / f).read_text()))
        assert used <= declared, f"{f}: undeclared {used - declared}"


def test_ci_uses_kit_layout_and_stages_an_artifact():
    ci = yaml.safe_load((ROOT / "pipelines" / "ci.yml").read_text())
    assert ci["resources"]["repositories"][0]["repository"] == "agentkit"
    text = (ROOT / "pipelines" / "ci.yml").read_text()
    assert "path: s/target" in text and "path: s/agentkit" in text and "git archive" in text
