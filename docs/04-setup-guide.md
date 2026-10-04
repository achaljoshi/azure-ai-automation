# 04 — Setup guide (step by step)

Commands assume Bash with Azure CLI logged in (`az login`). Replace values in `<>`.

## Step 0 — Variables

```bash
export LOCATION=uksouth
export RG=rg-ai-sdlc-poc
export ADO_ORG=https://dev.azure.com/<your-org>
export ADO_PROJECT=<your-project>
az extension add --name azure-devops --upgrade
az devops configure --defaults organization=$ADO_ORG project=$ADO_PROJECT
```

## Step 1 — Deploy supporting Azure resources

```bash
az group create -n $RG -l $LOCATION
az deployment group create -g $RG -f infra/main.bicep -p prefix=aisdlc
```

Creates: Log Analytics, App Insights, Key Vault, Storage, Function App (orchestrator), App Service plan + web app (test environment), Azure Load Testing. See [infra/main.bicep](../infra/main.bicep).

## Step 2 — Create the Foundry project and model deployments

1. In the Azure portal open **Microsoft Foundry** → create a project in `$LOCATION` (or reuse one).
2. Deploy two models:
   - **Primary** — a strong coding/reasoning model for the Dev and QA agents.
   - **Triage** — a small, cheap model for the Orchestrator (classification, readiness checks, dedupe).
3. Note the endpoint and deployment names. Store keys (if not using Entra auth) in Key Vault:
   ```bash
   az keyvault secret set --vault-name <kv-name> -n foundry-endpoint --value <endpoint>
   ```
4. Prefer **Entra ID (managed identity) auth** to the model endpoint over keys.

## Step 3 — Connect agents to Azure DevOps (MCP)

1. Confirm the ADO org is connected to Entra ID (Organization settings → Microsoft Entra).
2. Remote MCP Server endpoint: `https://mcp.dev.azure.com/<your-org>`.
3. In Foundry, add the Azure DevOps MCP tool to each agent and **limit toolsets per agent**:

| Agent | Toolsets |
|---|---|
| Orchestrator | `wit` (work items), `work`, `search` |
| Dev | `repos`, `wit`, `pipelines` (read) |
| QA | `wit`, `testplan`, `pipelines` (read), `repos` (read) |

4. Where a write operation you need isn't in the remote server yet (e.g. linking work items), the scripts fall back to the Azure DevOps REST API (`orchestrator/ado_client.py`).

## Step 4 — Configure Azure DevOps

```bash
bash scripts/setup-ado.sh
```

The script creates the area path, documents the tags, creates the `test` environment and prints the service-hook URLs to register. Then manually:

1. **Repos → Branches → main → Branch policies**: require 1 reviewer (human group), build validation (`pipelines/ci.yml`), linked work items, comment resolution. Under **Security**, deny "Bypass policies" for the agent identities.
2. **Project settings → Service hooks**: add Web Hooks for:
   - Work item created (filter: tag contains `ai-loop`)
   - Work item updated (filter: area path `AI-Loop`)
   - Run state changed (pipeline `deploy-test`, state Completed)
   Target URL: `https://<function-app>.azurewebsites.net/api/ado-events?code=<function-key>`
3. Create pipelines from YAML in `pipelines/`: `ci.yml`, `deploy-test.yml`, `dev-agent.yml`, `qa-agent.yml`. Note their pipeline IDs.

## Step 5 — Deploy the Orchestrator Function

```bash
cd orchestrator
cp local.settings.sample.json local.settings.json   # fill in values for local runs
func azure functionapp publish <function-app-name>
```

App settings to configure: `ADO_ORG_URL`, `ADO_PROJECT`, `DEV_AGENT_PIPELINE_ID`, `QA_AGENT_PIPELINE_ID`, `ITERATION_CAP` (default 3), `FOUNDRY_ENDPOINT`, `TRIAGE_DEPLOYMENT`, `KEY_VAULT_URI`.

## Step 6 — Agent prompts

Upload the system prompts from `agents/prompts/` into each Foundry agent (or let the pipeline runners load them from the repo). Keep prompts versioned in Git — a prompt change is a code change.

## Step 7 — Smoke test

1. Create a Bug in area `AI-Loop` with repro steps and expected result; add tag `ai-loop`.
2. Watch: Orchestrator comment appears → `dev-agent` pipeline runs → PR opens.
3. Approve and merge the PR → `deploy-test` runs → `qa-agent` runs.
4. Check the parent Bug for QA comments, child bugs or the `ai-ready-for-signoff` tag.

## Step 8 — Observability

- App Insights: orchestrator traces with `workItemId`, `iteration`, `agent`, `tokens_in`, `tokens_out`, `cost_estimate`.
- Pipeline artifacts: agent transcripts (`agent-transcript.jsonl`), test reports (Playwright HTML, JUnit, ZAP report, load test summary).
- Build a simple workbook: items in loop, iterations per item, escalations, tokens per item.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Service hook fires but nothing happens | Function key wrong or tag filter mismatch | Check Function logs; replay hook from ADO history |
| Dev agent can't push | Identity lacks Contribute on repo, or branch name blocked by policy | Grant Contribute + Create branch; use `ai/<id>-<slug>` branch prefix |
| Agent PR merges without review | Policy bypass permission left on | Deny "Bypass policies" for agent identities |
| MCP tool call fails with 401 | Org not Entra-backed or token audience wrong | Connect org to Entra; verify the agent identity has an ADO licence |
| Loop never ends | Exit criteria too loose or QA dedupe missing | Check iteration cap; enable dedupe (doc 05) |
| 429 from model | Quota/TPM too low | Raise quota, add retry with backoff, use triage model where possible |
