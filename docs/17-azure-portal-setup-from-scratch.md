# 17 — Azure setup from scratch, step by step (portal route)

This is the complete walkthrough for standing up the agent loop in your own Azure subscription and Azure DevOps organisation, using the **Azure portal** and the Azure DevOps web UI. Use it from any laptop: you only need a browser, `git`, and (for Phase 5) one command-line tool.

> **Honesty note.** Phases 1–2 were prepared and checked against the repository (the template compiles and is tested). Phases 3–6 are written from the product documentation and the code in this repo; portal menu names change now and then, so look for the **bold** names rather than exact positions. Nothing here has been run against your tenant yet. If a step behaves differently, stop and note the exact message — see [Troubleshooting](#troubleshooting).

**What you end up with:** a bug or story created in Azure Boards is triaged by the Orchestrator (an Azure Function), fixed by a Development agent in a pipeline (which opens a pull request), you review and merge, the change deploys to a test web app, a QA agent tests it, defects go back to the Development agent, and you sign off. Design: [docs/02](02-architecture.md), [docs/06](06-workflow-and-state-machine.md). What is implemented and tested: [docs/15](15-implementation-status.md).

---

## 0. Before you start

### 0.1 Accounts and access
| You need | Why | Check |
|---|---|---|
| An Azure subscription where you can create resources (**Owner**, or **Contributor** + **User Access Administrator**) | all Azure resources and role assignments | Portal → **Subscriptions** → your subscription → **Access control (IAM)** → *View my access* |
| A work or school account (Microsoft Entra ID) | the Azure DevOps organisation must be connected to Entra for the agents to sign in without tokens | you sign in to the portal with it |
| Permission to use Azure OpenAI / Microsoft Foundry in **UK South** | the agents' models | Portal → search *Azure OpenAI* → *Create*; if you are told access is restricted, request it first (it can take days) |

### 0.2 Tools on the laptop you will use for Phase 5
* `git`
* **Azure Functions Core Tools v4** — macOS: `brew install azure-functions-core-tools@4` · Windows: `winget install Microsoft.Azure.FunctionsCoreTools`
* (optional) Azure CLI — only if you prefer commands to clicking

### 0.3 Get this repository
```bash
git clone https://github.com/achaljoshi/azure-ai-automation.git
cd azure-ai-automation
git checkout feature/working-implementation      # until it is merged to main
```
The target project the agents will work on is the dashboard repo: `https://github.com/achaljoshi/html-reporting.git`, branch `feature/ai-agent-ready` (it contains all the bug fixes plus the agent setup; see section 4.3).

### 0.4 Fill in as you go (keep this list; later steps use it)
| Item | Your value |
|---|---|
| Subscription | |
| Resource group | `rg-ai-sdlc-poc` |
| Prefix | `aisdlc` |
| Function App name | `aisdlc-orchestrator-<suffix>` |
| Test web app name | `aisdlc-test-<suffix>` |
| Key Vault name | |
| Managed identity | `aisdlc-id-orchestrator` |
| Azure OpenAI endpoint | `https://<name>.openai.azure.com/` |
| Primary deployment name | |
| Triage deployment name | |
| Azure DevOps organisation URL | `https://dev.azure.com/<org>` |
| Azure DevOps project | `ai-sdlc-poc` |
| Function key (secret — do not write it in a file) | |
| Pipeline ids: dev-agent / qa-agent | |

### 0.5 Costs and cleanup
Idle cost is a few pounds a month (Basic web plan, storage, monitoring). Model calls and Azure Load Testing are pay-per-use. **To remove everything:** delete the resource group (section 9). Set a **budget alert**: Portal → **Cost Management + Billing → Budgets → Add**.

---

## Phase 1 — Azure DevOps organisation and project

1. Open **https://dev.azure.com** and sign in with the **same work account** as your Azure subscription.
2. **New organization** → choose a name and the **UK South** host region → continue.
3. In the organisation: **New project** → name `ai-sdlc-poc`, visibility **Private**, version control **Git**, work item process **Agile** → **Create**.
4. **Organization settings → Microsoft Entra**: it must show your tenant as connected. (If it says the organisation is not backed by a directory, connect it here. Without this the managed identity cannot be added later.)
5. **Request free pipeline minutes now** — new organisations have no free Microsoft-hosted parallel jobs, so pipelines will not start until you have them. Submit the form at **https://aka.ms/azpipelines-parallelism-request** (use the same email). Approval usually takes 2–3 business days. (Alternative: **Organization settings → Billing → Microsoft-hosted CI/CD → purchase 1 parallel job**.)
6. **Project settings → Boards → Project configuration → Areas → New child** → add `AI-Loop`. The loop watches this area.

✔ Done when: you can open `https://dev.azure.com/<org>/ai-sdlc-poc`, the Entra page shows your tenant, and the area path `ai-sdlc-poc\AI-Loop` exists.

---

## Phase 2 — Base Azure resources (resource group + template)

### 2.1 Resource group
Portal → **Resource groups → Create** → subscription: yours · name `rg-ai-sdlc-poc` · region **UK South** → **Review + create → Create**.

### 2.2 Deploy the template
Open this link while signed in to the portal (it loads `infra/main.json`, the compiled `infra/main.bicep`):

`https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fachaljoshi%2Fazure-ai-automation%2Ffeature%2Fworking-implementation%2Finfra%2Fmain.json`

(Once the branch is merged, replace `feature%2Fworking-implementation` with `main`.) Fill the form:

| Field | Value |
|---|---|
| Resource group | `rg-ai-sdlc-poc` |
| Prefix | `aisdlc` (lowercase, short) |
| Location | leave default |
| Ado Org Url / Ado Project | blank for now (set in Phase 5) |
| Foundry Endpoint / Triage Deployment / Primary Deployment | blank for now (set in Phase 5) |
| Dev / Qa Agent Pipeline Id | `0` for now |
| Human Owner | your work email — escalations are assigned to this person |
| Llm Provider | `azure` |
| Iteration Cap · Token Budget · Wallclock Budget Seconds | defaults (3 · 2,000,000 · 14,400) |

**Review + create → Create** (3–5 minutes).

What it creates (about 10 resources): Log Analytics workspace, Application Insights, Storage account, Key Vault (RBAC mode), user-assigned managed identity `aisdlc-id-orchestrator`, a Function plan + **Function App** (the orchestrator, Python 3.11, uses that identity), a Basic web plan + **test web app** (Node 20), and an Azure Load Testing resource.

✔ Done when: the resource group lists those resources and the deployment shows **Succeeded**. Write the Function App, web app and Key Vault names into the table in 0.4.

---

## Phase 3 — Azure OpenAI (models) and permissions

### 3.1 Create the Azure OpenAI resource
Portal → **Create a resource** → search **Azure OpenAI** → **Create**: subscription yours · resource group `rg-ai-sdlc-poc` · region **UK South** · name e.g. `aoai-ai-sdlc-<yourinitials>` · pricing tier **Standard S0** → **Next** (leave network as *All networks* for the proof of concept) → **Create**.

### 3.2 Deploy two models
Open the resource → **Go to Azure AI Foundry portal** (or **Model deployments → Manage deployments**) → **Deployments → Deploy model → Deploy base model**.

1. **Primary (coding/reasoning)** — the strongest chat model with **tool/function calling** that is available to you in UK South. Deployment name e.g. `primary`. Set tokens-per-minute to what your quota allows (start at 50–100K).
2. **Triage (cheap)** — a small, fast chat model with function calling. Deployment name e.g. `triage`. 30–50K TPM is plenty.

Model availability depends on your subscription and region; the portal only lists what you can deploy. If no strong model is available, request quota (Foundry portal → **Quotas**) and continue with other phases meanwhile.

Note down: the **endpoint** (resource → **Keys and Endpoint** → *Endpoint*, like `https://aoai-ai-sdlc-xx.openai.azure.com/`) and the two **deployment names**. You do **not** need the keys: the loop signs in with Entra identities.

### 3.3 Let the orchestrator call the models
Azure OpenAI resource → **Access control (IAM) → Add → Add role assignment** → role **Cognitive Services OpenAI User** → Members: **Managed identity → Select members → User-assigned managed identity →** `aisdlc-id-orchestrator` → **Review + assign**.

(The pipelines' identity gets the same role in Phase 4.5.)

✔ Done when: two deployments show **Succeeded** and the role assignment appears under IAM → *Role assignments*.

---

## Phase 4 — Azure DevOps wiring

### 4.1 Import the repositories
Azure DevOps → **Repos → Files → (repo drop-down) → Import repository**.

1. Clone URL `https://github.com/achaljoshi/azure-ai-automation.git` → name **`ai-agentkit`** (the pipelines refer to this exact name).
2. Clone URL `https://github.com/achaljoshi/html-reporting.git` → name `html-reporting` (the project the agents will work on).

Decide which branches the pipelines see. **Recommended:** before importing, merge `feature/working-implementation` into `main` of azure-ai-automation and `feature/ai-agent-ready` into `main` of html-reporting on GitHub (review the pull requests first). If you import without merging, the work is on the feature branches: in the imported repos set the default branch to those (**Repos → Branches → ⋯ → Set as default branch**) and, in each pipeline YAML, add `ref: refs/heads/feature/working-implementation` under the `agentkit` repository resource.

### 4.2 Put the pipeline files in the target repository
The pipelines live in the **target** repo (`html-reporting`) and use `ai-agentkit` as a resource. On any laptop:

```bash
git clone https://dev.azure.com/<org>/ai-sdlc-poc/_git/html-reporting     # sign in when asked
cd html-reporting
git checkout -b add-agent-pipelines
cp -r ../azure-ai-automation/pipelines ./pipelines
git add pipelines && git commit -m "Add agent pipelines" && git push -u origin add-agent-pipelines
```
Open the pull request in Azure DevOps and **merge it yourself** (agents are never allowed to edit `pipelines/`; humans do). The target repo also needs `.agent/project.json` and `AGENTS.md` — they are already in the `feature/ai-agent-ready` branch.

### 4.3 Environments
**Pipelines → Environments → New environment** → `test` (resource: None, no approvals). Optionally create `prod` with a manual **Approvals** check and **do not** give agent identities access to it.

### 4.4 Service connection to Azure
**Project settings → Service connections → New service connection → Azure Resource Manager → Workload identity federation (automatic)** → scope level **Subscription** → your subscription → resource group `rg-ai-sdlc-poc` → name **`sc-ai-sdlc-poc`** (the pipelines use this exact name) → *Grant access permission to all pipelines* (acceptable for this proof of concept; tighten later) → **Save**.

### 4.5 Give the pipelines' identity access to the models
Open the new service connection → **Manage App registration** (or **Manage service principal**) to see its name. Then Azure OpenAI resource → **IAM → Add role assignment** → **Cognitive Services OpenAI User** → **User, group, or service principal** → select that app registration → assign. (It also gets **Contributor** on `rg-ai-sdlc-poc` automatically from the service connection scope; the test web app deployment uses that.)

### 4.6 Variable group
**Pipelines → Library → + Variable group** → name **`ai-agents`**. Add:

| Variable | Value | Secret? |
|---|---|---|
| `LLM_PROVIDER` | `azure` | no |
| `FOUNDRY_ENDPOINT` | your Azure OpenAI endpoint | no |
| `PRIMARY_DEPLOYMENT` | e.g. `primary` | no |
| `OPENAI_API_VERSION` | `2024-10-21` | no |
| `ORCHESTRATOR_URL` | filled in Phase 5.3 (contains the function key) | **yes** |
| `TEST_BASE_URL` | `https://<test web app name>.azurewebsites.net` | no |
| `TEST_WEBAPP_NAME` | the test web app name | no |
| `TEST_START_COMMAND` | `node tools/serve.js` (starts the dashboard on the web app) | no |
| `QA_AGENT_PIPELINE_ID` | filled in 4.8 | no |

Click the lock icon for secrets, then **Save**. (To use Claude instead of Azure OpenAI later: set `LLM_PROVIDER=anthropic` and add `ANTHROPIC_API_KEY` as a **secret** here.)

### 4.7 Permissions the pipelines need on the repository
**Project settings → Repositories → html-reporting → Security** → find **`ai-sdlc-poc Build Service (<org>)`** → set **Contribute**, **Create branch**, **Contribute to pull requests** to *Allow*, and **Bypass policies when pushing / completing pull requests** to **Deny** (or leave unset). Do the same under **Repositories → (all repositories)** if the build service is not listed per repo.

### 4.8 Create the four pipelines
**Pipelines → New pipeline → Azure Repos Git → html-reporting → Existing Azure Pipelines YAML file** → path, then **Save** (do not run yet) and **rename** each pipeline (⋯ → Rename) exactly:

| YAML path | Pipeline name (must match) |
|---|---|
| `/pipelines/ci.yml` | `ci` |
| `/pipelines/deploy-test.yml` | `deploy-test` (it triggers from the pipeline named `ci`) |
| `/pipelines/dev-agent.yml` | `dev-agent` |
| `/pipelines/qa-agent.yml` | `qa-agent` |

The pipeline **id** is the number in the browser address bar (`…definitionId=NN`) when you open it. Write down `dev-agent` and `qa-agent` ids. Put the QA id in the variable group (`QA_AGENT_PIPELINE_ID`). The first run of each pipeline asks you to **Permit** access to the variable group, service connection, environment and the `ai-agentkit` repository — click **Permit** each time.

### 4.9 Branch policy on `main`
**Repos → Branches → main → ⋯ → Branch policies**: **Require a minimum number of reviewers** 1 (a human) · **Build validation** → add the `ci` pipeline · **Check for linked work items** (required) · **Check for comment resolution** (required). This is what keeps a human in charge: no agent output reaches `main` unreviewed.

✔ Done when: `ci` runs green on `main` (it installs, builds, runs unit tests and stages the artifact), and you have the two pipeline ids.

---

## Phase 5 — Deploy the orchestrator and connect Azure DevOps to it

### 5.1 Let the orchestrator talk to Azure DevOps
The orchestrator runs as the managed identity `aisdlc-id-orchestrator`, so that identity must exist in your Azure DevOps organisation:

1. **Organization settings → Users → Add users**.
2. In the user field enter `aisdlc-id-orchestrator` (the managed identity's name; you can also search by its client/object id from Portal → the identity → **Overview**). Access level **Basic**, add to project `ai-sdlc-poc` as **Contributor** → **Add**.
3. The identity needs to read/write work items and queue the `dev-agent` pipeline: **Project settings → Permissions → Contributors** already gives work-item rights; for pipelines open **Pipelines → dev-agent → ⋯ → Manage security** and allow **Queue builds** for that identity.

If the identity cannot be found, confirm Phase 1 step 4 (organisation connected to Entra) and that you are in the same tenant. Azure DevOps lists this as *service principals & managed identities*.

### 5.2 Deploy the code
On a laptop with Core Tools (section 0.2), signed in to Azure (`az login` or `func azure functionapp publish` will prompt):

```bash
cd azure-ai-automation
bash scripts/publish_orchestrator.sh <your-function-app-name>
```

The script copies the triage prompt into the package (the Function only deploys the `orchestrator/` folder) and publishes with a remote build. Then in the portal: Function App → **Functions** — you should see `ado_events` and `sweep`.

### 5.3 Settings and the webhook URL
Update the Function App settings. **Easiest:** rerun the deployment from Phase 2.2 into the same resource group with the real values (Ado Org Url, Ado Project, Foundry Endpoint, deployments, pipeline ids, Human Owner) — it updates the app settings in place. **Or:** Function App → **Settings → Environment variables → App settings** and set: `ADO_ORG_URL`, `ADO_PROJECT`, `FOUNDRY_ENDPOINT`, `TRIAGE_DEPLOYMENT`, `PRIMARY_DEPLOYMENT`, `DEV_AGENT_PIPELINE_ID`, `QA_AGENT_PIPELINE_ID`, `HUMAN_OWNER`, and optionally `AGENT_IDENTITIES` (comma-separated emails of agent accounts so their own edits never re-trigger triage). **Apply**, then **Restart** the app.

Get the key: Function App → **Functions → App keys → Host keys → default** (copy it).
Webhook URL: `https://<function-app>.azurewebsites.net/api/ado-events?code=<key>`
Put that full URL (it is a secret) in the variable group as `ORCHESTRATOR_URL` (secret).

### 5.4 Service hooks (Azure DevOps → orchestrator)
**Project settings → Service hooks → Create subscription → Web Hooks → Next**, create two:

1. **Trigger:** *Work item created* — filters: **Area path** `ai-sdlc-poc\AI-Loop` (and tag contains `ai-loop` if offered). **Action:** URL = the webhook URL above → **Test** (expect a 2xx/202) → **Finish**.
2. **Trigger:** *Work item updated* — same filters, same URL.

(The loop's other events — dev result, QA started, QA verdict — are posted by the pipelines themselves using `ORCHESTRATOR_URL`.)

✔ Done when: the **Test** button on both hooks returns success, and Function App → **Monitor** shows the test invocation.

---

## Phase 6 — Smoke test: one bug end to end

1. **Boards → Work items → New work item → Bug**. Title e.g. `Dates typed as 9/25/2026 are rejected`. Set **Area** `ai-sdlc-poc\AI-Loop`. Add **Tags**: `ai-loop`. Fill in **Repro steps** (steps, expected, actual), then **Save**.
2. Within a minute a comment from **Orchestrator** appears and the item gets tags `ai-owner:dev`, `ai-iter:1`, and state **Active**. (If it asks for more information it tags `ai-needs-info`; answer it and save to re-trigger.) The `dev-agent` pipeline starts — *this needs the parallel-jobs approval from Phase 1.5*.
3. The Development agent works on branch `ai/<id>`, the pipeline re-runs build and tests itself, checks the diff policy and opens a **pull request**. You review and **complete the PR** (merge to `main`).
4. The `ci` run on `main` triggers **deploy-test**, which deploys to the test web app, tags the item `ai-owner:qa`, and starts **qa-agent**.
5. The QA agent writes tests, the pipeline runs the full suites itself, and the result lands on the work item: either child bugs (the loop goes round again, up to the iteration cap of 3, then escalates to your **Human Owner**) or the tag **`ai-ready-for-signoff`** — that is your cue to review and close the item.

### Watching it work
* Application Insights → **Logs**: `traces | where message has "ai_loop_decision" | order by timestamp desc` shows every routing decision (item, action, reason, iteration).
* Pipelines → each run → **Artifacts**: agent transcripts (`dev-transcript-it*`, `qa-transcript-*`) and the Playwright report.
* The work item **History** and **Discussion** show every comment and tag change.

---

## Phase 7 — Hardening checklist (before real use)
* [ ] Agent identities **cannot** approve PRs or bypass policies (Project settings → Repositories → Security).
* [ ] `prod` environment has a manual approval and no agent access.
* [ ] Service connection scope narrowed from "all pipelines" to the four pipelines.
* [ ] Function App: restrict inbound access (Networking) or keep the function key secret; rotate the key if it ever leaks.
* [ ] Budgets and alerts set (Cost Management); token budget (`TOKEN_BUDGET`) and wall-clock budget reviewed.
* [ ] Key Vault: move secrets there if you add any (the template creates the vault; nothing requires it yet).
* [ ] Read [docs/09](09-security-and-governance.md) and [docs/12](12-risks-and-faq.md).

## 8. Optional: run the loop on your own machine instead
You can exercise the whole loop without Azure DevOps, using any git repository (see [docs/15](15-implementation-status.md)):

```bash
python agents/local_loop.py --repo ../html-reporting --task "Bug: ..." --type bug
```

## 9. Clean-up
Portal → **Resource groups → rg-ai-sdlc-poc → Delete resource group** (type the name to confirm). Then delete the Azure DevOps project (**Project settings → Overview → Delete**) and, if you want, the organisation (**Organization settings → Overview → Delete**). Azure OpenAI and Key Vault are soft-deleted for a while; purge them if you need the names back.

---

## Troubleshooting
| Symptom | Likely cause | What to do |
|---|---|---|
| Template deployment fails with a quota error for the Function or web plan | new subscriptions often have zero quota for a plan type in a region | open the failed deployment → **Operation details**; request quota (Subscriptions → Usage + quotas) or ask to switch the plan SKU in `infra/main.bicep` |
| "Resource provider not registered" | provider not enabled | Subscriptions → **Resource providers** → register `Microsoft.Web`, `Microsoft.KeyVault`, `Microsoft.CognitiveServices`, `Microsoft.LoadTestService`, `Microsoft.OperationalInsights` |
| Pipeline stays queued: "No hosted parallelism" | free minutes not granted yet | Phase 1.5; check the request email, or purchase 1 parallel job |
| Service hook **Test** fails with 401/403 | wrong or missing function key | recopy the host key; the URL must end `?code=<key>` |
| Work item created but nothing happens | tag or area filter mismatch, or hook not saved | confirm the bug has the area `AI-Loop` and tag `ai-loop`; **Service hooks → History** shows what was sent |
| Orchestrator comments "no usable answer" / 500 in Function logs | model call failing: identity role missing or wrong endpoint/deployment names | check Phase 3.3 role assignment, `FOUNDRY_ENDPOINT` (ends `.openai.azure.com/`), `TRIAGE_DEPLOYMENT` |
| Function log: *orchestrator prompt not found* | published without the script | run `bash scripts/publish_orchestrator.sh <app>` |
| 401/403 from Azure DevOps in the Function log | the managed identity is not in the organisation or lacks rights | Phase 5.1 |
| `dev-agent` fails at checkout of `agentkit` | repo name differs from `ai-agentkit` or not permitted | rename the repo / click **Permit** on the pipeline run |
| `dev-agent` cannot push the `ai/<id>` branch | build service lacks Contribute / Create branch | Phase 4.7 |
| Agent PR merged without review | policy bypass left on | Phase 4.9 and 4.7 |
| 429 from the model | tokens-per-minute quota too low | raise TPM on the deployment; use the triage model for cheap steps |
| `deploy-test` cannot find the artifact | pipeline not named `ci` | Phase 4.8 naming |

## Quick reference — names that must match
`ai-agentkit` (repo) · `sc-ai-sdlc-poc` (service connection) · `ai-agents` (variable group) · `ci`, `deploy-test`, `dev-agent`, `qa-agent` (pipelines) · `test` (environment) · `ai-sdlc-poc\AI-Loop` (area path) · tag `ai-loop` (opts an item into the loop).
