# 03 — Setup requirements

## Accounts and licences

| Item | Needed for | Notes |
|---|---|---|
| Azure subscription | All Azure resources | Owner or Contributor + User Access Administrator on the resource group |
| Microsoft Entra ID tenant | Auth for Azure DevOps and the Remote MCP Server | The Azure DevOps org **must be connected to Entra ID** for the Remote MCP Server |
| Azure DevOps organization | Boards, Repos, Pipelines | First 5 Basic users are free |
| Azure DevOps Basic licence for each agent identity | Agents act as users/service principals | Service principals / managed identities can be added to the org |
| Basic + Test Plans (optional) | If you want QA agent results in Azure Test Plans | Expensive per user — optional for PoC |
| Microsoft Foundry project | Model deployments + Agent Service | Region must offer the models you choose |
| Model quota | Coding / reasoning model + small triage model | Request quota early; it is often the slowest step |

## Identities

| Identity | Type | Permissions |
|---|---|---|
| `id-ai-orchestrator` | User-assigned managed identity (Function App) | ADO: read/write work items, queue pipelines. Azure: Key Vault secrets get |
| `sp-ai-dev-agent` | Service principal / workload identity | ADO: Contribute to repo (branches only — **no bypass of policies**), create PRs, read/write work items |
| `sp-ai-qa-agent` | Service principal / workload identity | ADO: read repo, read/write work items, read pipelines, publish test results |
| Human reviewers | Users | Required PR reviewers; release approvers |

Rule of thumb: **no agent identity can approve a PR, bypass branch policies, or deploy beyond the test environment.**

## Local tooling (for building the PoC)

| Tool | Version (min) | Purpose |
|---|---|---|
| Azure CLI | 2.60+ | Resource deployment, `az devops` extension |
| `azure-devops` CLI extension | latest | Scripted ADO setup (`az extension add --name azure-devops`) |
| Bicep | bundled with Azure CLI | Infra in `infra/` |
| Python | 3.11+ | Orchestrator Function, agent runners |
| Azure Functions Core Tools | v4 | Local function runs |
| Node.js | 20 LTS | Playwright, axe-core, MCP local server fallback |
| Playwright | latest | UI tests run by the QA agent |
| Git | 2.40+ | |
| VS Code + GitHub Copilot / MCP-capable client | optional | For exploring the ADO MCP server interactively |

## Azure DevOps project configuration

- Process: **Agile** (inherited) — gives Bug and User Story with Acceptance Criteria field
- Tags used by the loop: `ai-loop`, `ai-owner:orchestrator`, `ai-owner:dev`, `ai-owner:qa`, `ai-iter:N`, `ai-escalated`, `ai-ready-for-signoff`, `ai-raised`
- Area path for the PoC: `<Project>\AI-Loop`
- Branch policies on `main`: min 1 human reviewer, build validation, linked work item required, comment resolution required
- Environments: `test` (no approval), `prod` (manual approval — agents have no access)
- Service hooks: Work item created, Work item updated → Orchestrator Function URL; Run state changed (deploy-test stage) → Orchestrator Function URL

## Network and data

- Agents call models in your Foundry project — choose a region that matches your data residency needs (for UK clients, UK South)
- The test environment must be reachable from the pipeline agents that run the QA agent (Microsoft-hosted agents or self-hosted in a VNet)
- No production data in the test environment. Use seeded synthetic data

## System under test (SUT)

Pick something small and well-tested for the first runs: one web app with a REST API, a UI with 3–5 pages, an existing unit test project, and a deploy pipeline that already works. A seeded list of 10–20 known bugs gives you a repeatable benchmark.

## Readiness checklist

- [ ] Subscription + resource group created
- [ ] ADO org connected to Entra ID
- [ ] Foundry project created, two models deployed, quota confirmed
- [ ] Agent identities created and added to ADO with least privilege
- [ ] Branch policies on `main` enforced, agents cannot bypass
- [ ] Test environment deploys from a pipeline today, by hand-triggered run
- [ ] Seeded bug list ready
- [ ] Budget alert set on the resource group (see doc 08)
