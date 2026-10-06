import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("az"), reason="Azure CLI (az bicep) not installed")
def test_bicep_compiles_and_exposes_every_env_var_the_function_reads():
    r = subprocess.run(["az", "bicep", "build", "--file", str(ROOT / "infra" / "main.bicep"), "--stdout"], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr[-800:]
    arm = json.loads(r.stdout)
    names = {s["name"] for res in arm["resources"] if res["type"] == "Microsoft.Web/sites" for s in res["properties"]["siteConfig"]["appSettings"]}
    code = (ROOT / "orchestrator" / "function_app.py").read_text() + (ROOT / "orchestrator" / "ado_client.py").read_text() + (ROOT / "orchestrator" / "llm.py").read_text()
    import re
    wanted = set(re.findall(r'os\.environ(?:\.get)?\(?\[?"([A-Z_]+)"', code)) - {"ANTHROPIC_MODEL", "ANTHROPIC_TRIAGE_MODEL", "OPENAI_API_VERSION", "SYSTEM_COLLECTIONURI", "SYSTEM_TEAMPROJECT"}
    assert wanted <= names, f"missing app settings: {sorted(wanted - names)}"


@pytest.mark.skipif(not shutil.which("az"), reason="Azure CLI (az bicep) not installed")
def test_committed_arm_json_matches_the_bicep():
    """infra/main.json is what the portal's 'Deploy to Azure' link uses; it must be regenerated whenever main.bicep changes:
       az bicep build --file infra/main.bicep --outfile infra/main.json"""
    r = subprocess.run(["az", "bicep", "build", "--file", str(ROOT / "infra" / "main.bicep"), "--stdout"], capture_output=True, text=True, timeout=180)
    fresh = json.loads(r.stdout)
    committed = json.loads((ROOT / "infra" / "main.json").read_text())
    fresh["metadata"].pop("_generator", None); committed["metadata"].pop("_generator", None)
    assert fresh == committed, "infra/main.json is stale - regenerate it from main.bicep"
