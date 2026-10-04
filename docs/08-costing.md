# 08 — Costing

> All prices in USD, list price, reviewed **October 2026**. Always confirm with the [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/) for your region and agreement. Model token prices change frequently — the figures marked *assumption* are placeholders to plug your real rates into. The interactive calculator in [demo/index.html](../demo/index.html) lets you change every input.

## 1. Fixed monthly platform costs

| Item | Price (list) | PoC quantity | Monthly |
|---|---|---|---|
| Azure DevOps Basic users | First 5 free, then $6/user/month | 5 humans + 3 agent identities = 8 | $18 |
| Microsoft-hosted parallel job | 1 free (1,800 min/month); $40 per extra | +1 (agents and CI run concurrently) | $40 |
| Self-hosted parallel job (alternative) | 1 free; $15 per extra | 0 | $0 |
| Basic + Test Plans (optional) | $52/user/month | 0 for PoC | $0 |
| App Service plan B1 (test env) | ~ $13/month (Linux) *verify* | 1 | ~$13 |
| Function App (Consumption / Flex) | Free grant usually covers PoC volume *verify* | 1 | ~$0–5 |
| Storage, Key Vault | Pennies at PoC scale | — | ~$2 |
| Log Analytics + App Insights | Pay per GB ingested *verify regional rate* | ~2–5 GB | ~$5–15 |
| Azure Load Testing | Monthly resource fee + per virtual-user-hour *verify* | 1 resource, ~50 VUH | ~$15–20 |
| **Platform subtotal** | | | **≈ $95–115 / month** |

## 2. Variable AI (token) cost — the part that matters

Cost per work item = Σ over iterations of (orchestrator + dev agent + QA agent tokens) × price.

### Token assumptions per iteration (measure and replace)

| Agent | Input tokens | Output tokens | Model |
|---|---|---|---|
| Orchestrator (triage, routing, dedupe) | 15k | 2k | Triage (small) |
| Dev agent (read code, edit, retries) | 400k | 40k | Primary |
| QA agent (design, generate, triage) | 250k | 30k | Primary |

Agentic coding is input-heavy because the agent re-reads files and logs each turn. **Prompt caching** (where the model supports it) can cut input cost substantially — enable it.

### Price assumptions (*placeholders — set from your Foundry deployment's pricing page*)

| Model tier | Input $/1M | Output $/1M |
|---|---|---|
| Primary (coding/reasoning) | $2.50 | $10.00 |
| Triage (small) | $0.20 | $0.80 |

### Worked example

Per iteration:
- Orchestrator: 15k × $0.20/1M + 2k × $0.80/1M ≈ $0.005
- Dev: 400k × $2.50/1M + 40k × $10/1M = $1.00 + $0.40 = $1.40
- QA: 250k × $2.50/1M + 30k × $10/1M = $0.625 + $0.30 ≈ $0.93
- **≈ $2.33 per iteration**

| Scenario | Iterations | Cost per item |
|---|---|---|
| Simple bug | 1–2 | $2.30–$4.70 |
| Small story | 2–3 | $4.70–$7.00 |
| Escalated item (cap 3 + wasted work) | 3 | ~$7.00 + human time |

Monthly (PoC volume: 40 bugs × 1.6 iterations + 15 stories × 2.4 iterations = 100 iterations): **≈ $233 tokens + ~$105 platform ≈ $340/month**.

## 3. Pipeline minutes

| Activity | Minutes per iteration |
|---|---|
| Dev agent job | 10–20 |
| PR build validation | 5–10 |
| Deploy to test | 5 |
| QA agent job (incl. regression, ZAP baseline) | 15–30 |
| **Total** | **35–65** |

100 iterations × ~50 min = 5,000 min/month — well past the free 1,800 minutes, so budget at least one paid Microsoft-hosted job ($40) or run agents on a self-hosted agent ($15 per extra job + VM cost).

## 4. Human time (do not forget it)

| Activity | Per item |
|---|---|
| Writing a good work item (AC, repro) | 10–20 min |
| PR review (per iteration) | 10–20 min |
| Sign-off | 5–10 min |
| Handling escalations | 30–90 min (only for escalated items) |

The business case is **not** "no humans". It is moving humans from doing the loop to deciding at its gates.

## 5. ROI framing

```
Saving per item = (human baseline hours − human hours with agents) × blended rate − AI cost per item
```

Example: baseline 6 h of dev+test effort for a small bug, 1 h with agents (writing + review + sign-off), blended rate $50/h, AI cost $4 → saving ≈ $246 per bug. Only count items that closed **without** escalation; escalated items usually cost more than the baseline.

## 6. Cost controls

- Budget + alert on the resource group (`az consumption budget create`) at 50/80/100%.
- Per-item token budget enforced by the orchestrator (doc 06).
- Use the triage model for anything that is classification, summarisation or dedupe.
- Enable prompt caching; trim logs before sending (last 200 lines + error fingerprints).
- Run full performance and full ZAP scans nightly, not per iteration.
- Stop the App Service test env outside working hours (or use deployment slots on a single plan).

## 7. Scale-up view (team of 20, production pilot)

| Item | Monthly |
|---|---|
| ADO Basic: 20 humans + 3 agents (5 free) | $108 |
| 3 extra Microsoft-hosted parallel jobs | $120 |
| Test env: S1/P0v3 plan + slots | ~$70–150 |
| Monitoring | ~$50–100 |
| Load testing | ~$50–150 |
| Tokens: ~600 iterations × $2.33 | ~$1,400 |
| **Indicative total** | **≈ $1,800–2,050** |
