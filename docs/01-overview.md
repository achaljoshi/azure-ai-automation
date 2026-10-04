# 01 — Overview

## Problem

Delivery teams spend a large share of each sprint on repeatable loops: reproduce a bug, fix it, write a unit test, deploy, retest, log the regression, fix again. Each hand-off between developer and tester adds waiting time. This R&D asks a simple question:

> **Can AI agents run the dev ↔ test loop on Azure, end to end, with humans only at the decision points?**

## Goal

Build a working proof of concept where:

1. A human creates a **Bug** or **User Story** in Azure Boards with clear acceptance criteria.
2. An **Orchestrator agent** triages it, checks it is ready, and assigns it to the **Development agent**.
3. The Development agent creates a branch in **Azure Repos**, implements the change with unit tests, and raises a **pull request** linked to the work item.
4. PR quality gates run (build, unit tests, static analysis, secret scan). A **human approves the merge**.
5. **Azure Pipelines** deploys the build to a **test environment**.
6. The **QA agent** generates and runs tests from the acceptance criteria — functional (UI, API), regression, and non-functional (performance, security, accessibility).
7. Each failure becomes a new **Bug** linked to the parent item and assigned back to the Development agent.
8. The loop repeats until the **exit criteria** are met, or the **iteration cap** is reached and a human takes over.
9. A **human signs off** the release.

## In scope

- Azure Boards, Azure Repos, Azure Pipelines (Azure DevOps Services)
- Microsoft Foundry (models + Agent Service) for the agents
- Azure DevOps Remote MCP Server for agent access to Boards, Repos, Pipelines, Test Plans
- An Azure Function for event routing (service hooks → agents)
- A small sample application as the system under test
- Playwright (UI), REST-level API tests, Azure Load Testing (performance), OWASP ZAP baseline (security), axe-core (accessibility)

## Out of scope (for the PoC)

- Production deployments by agents (agents never deploy beyond test)
- Agents approving their own PRs
- Multi-repo / microservice-wide changes
- Database schema migrations on shared environments

## Two delivery options

| | **Option A — Azure Repos (primary)** | **Option B — GitHub repo + Azure Boards** |
|---|---|---|
| Code host | Azure Repos | GitHub |
| Development agent | Custom agent (Foundry model) running inside an Azure Pipelines job | GitHub Copilot coding agent, started from the Azure Boards work item |
| Effort to build | Higher — you build the dev agent runner | Lower — dev agent is off the shelf |
| Control | Full control of prompts, tools, model, data residency | Bound by Copilot's capabilities and licensing |
| Fit with your requirement | Exact (Azure Repos) | Requires moving code to GitHub |

The Copilot coding agent integration with Azure Boards does **not** support Azure Repos — only GitHub repositories. That is why Option A uses a custom dev agent. See [14-alternative-github-copilot.md](14-alternative-github-copilot.md) for Option B.

## Success criteria for the R&D

| Measure | Target for PoC |
|---|---|
| Bugs fixed end-to-end without human code edits | ≥ 50% of a seeded bug set |
| Stories closed within iteration cap (3) | ≥ 40% of small stories |
| Escaped defects found by human review after sign-off | Tracked, trending down |
| Mean time from "bug created" to "fixed in test env" | Measured vs. human baseline |
| Cost per closed work item | Measured, see [08-costing.md](08-costing.md) |

## Glossary

| Term | Meaning |
|---|---|
| Loop / iteration | One pass of Dev agent → deploy → QA agent |
| Iteration cap | Maximum loops before escalation to a human (default 3) |
| Exit criteria | Machine-checkable conditions that end the loop (see doc 06) |
| Parent item | The original Bug or Story; QA-raised bugs link to it as children |
| MCP | Model Context Protocol — the standard agents use to call tools |
