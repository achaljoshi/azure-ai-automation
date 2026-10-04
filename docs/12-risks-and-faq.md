# 12 — Risks, limitations and FAQ

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Agents produce plausible but wrong fixes | High | High | Test-first fixes, human PR review, QA agent designs tests before seeing the diff |
| Fix-A-breaks-B oscillation | Medium | Medium | Iteration cap, oscillation detector, escalation |
| Poor work item quality | High | High | Orchestrator readiness check; templates with AC and repro fields |
| Flaky tests create noise bugs | High | Medium | Re-run, flaky tracking, quarantine owned by humans |
| Token cost overruns | Medium | Medium | Per-item budgets, cheap triage model, caching |
| Model quota / throttling | Medium | Medium | Request quota early; backoff; queue |
| Preview features change | Medium | Medium | Thin adapters (`ado_client.py`); pin API versions |
| Prompt injection | Low–Med | High | See doc 09 |
| Reviewer fatigue (rubber-stamping agent PRs) | Medium | High | Small diffs, clear PR summaries, review sampling |

## Known limitations (October 2026)

- GitHub Copilot coding agent from Azure Boards works only with GitHub repos, not Azure Repos.
- The Azure DevOps Remote MCP Server doesn't yet expose every write operation (e.g. linking work items) — use the REST fallback.
- Some MCP clients can't authenticate to the Remote MCP Server yet because of Entra client-registration support; use Foundry, Copilot Studio, VS Code or the local MCP server.
- Agents are weakest on: large cross-cutting refactors, ambiguous requirements, UI visual judgement, and performance root-cause analysis.

## FAQ

**Does this replace testers and developers?**
No. It moves people from executing the loop to defining work, reviewing changes and deciding releases. Expect gains on well-specified, small-to-medium items.

**Why not let the QA agent fix the bugs it finds?**
Separation of duties. The tester and the fixer being the same agent hides mistakes, just as with people.

**Why does the Dev agent run inside a pipeline, not just in Foundry?**
It needs a real workspace to clone, build and run tests. The pipeline job gives a clean, logged, disposable sandbox.

**Why tags instead of custom states?**
Faster to set up on the stock Agile process. Move to custom states once the flow is stable.

**Can it work with SAP GUI / desktop apps?**
The loop is the same; only the QA agent's tools change (e.g. desktop automation frameworks). Start with a web app.

**What if the model is wrong about severity?**
Severity rules are explicit (doc 07); humans can override, and overrides are tracked as a quality metric.

**Can we use Claude or other non-Microsoft models?**
Foundry hosts models from several providers; the agent runner talks to an OpenAI-compatible chat endpoint, so the model is a configuration choice. Check regional availability and the client's data terms.
