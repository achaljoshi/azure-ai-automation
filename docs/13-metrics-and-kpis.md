# 13 — Metrics and KPIs

| KPI | Definition | Source |
|---|---|---|
| Autonomous close rate | Items reaching `ai-ready-for-signoff` without escalation ÷ items entering loop | Boards tags |
| Iterations per item | Mean `ai-iter` at exit | Boards tags |
| Escalation rate | Items tagged `ai-escalated` ÷ items entering loop | Boards tags |
| Lead time | Created → ready-for-signoff | Boards history |
| PR acceptance rate | Agent PRs merged without human code changes ÷ agent PRs | Repos |
| Review effort | Human review minutes per PR (sampled) | Survey / PR timestamps |
| Escaped defects | Bugs found after sign-off linked to agent-closed items | Boards |
| QA bug precision | QA-raised bugs confirmed valid by humans ÷ QA-raised bugs | Boards (triage field) |
| Duplicate bug rate | QA bugs closed as duplicate ÷ QA bugs | Boards |
| Cost per closed item | Tokens × price + pipeline minutes share | Telemetry |
| Test asset growth | New automated tests added per item | Repo |

Starter Kusto query (App Insights custom events from the orchestrator):

```kusto
customEvents
| where name == "ai_loop_iteration"
| extend workItemId = tostring(customDimensions.workItemId),
         iteration = toint(customDimensions.iteration),
         costUsd = todouble(customDimensions.cost_estimate)
| summarize iterations = max(iteration), cost = sum(costUsd) by workItemId
| summarize avgIterations = avg(iterations), avgCost = avg(cost), items = count()
```
