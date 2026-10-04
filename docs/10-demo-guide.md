# 10 — Demo guide

Two ways to demo: the **interactive simulation** (no Azure needed, 10 minutes) and the **live demo** (real Azure DevOps, 25–30 minutes).

## A. Interactive simulation — `demo/index.html`

Open the file in any browser (or publish with GitHub Pages: Settings → Pages → Deploy from branch `main`, folder `/` → `https://<user>.github.io/azure-ai-automation/demo/`).

What it shows:
- The loop as a live track: Boards → Orchestrator → Dev agent → PR gates → Deploy → QA agent → Exit check → Sign-off.
- A mini Azure Boards with the parent item and QA-raised bugs moving across columns.
- An agent console streaming what each agent is doing.
- Live counters: iteration, open bugs, tokens, estimated cost, elapsed simulated time.
- Three scenarios:
  1. **Bug fix** — fixed in 2 iterations after QA catches a regression.
  2. **New feature** — 3 iterations; functional, performance and accessibility defects.
  3. **Stubborn defect** — hits the iteration cap and escalates to a human (shows the guardrail).
- A **cost calculator** with editable token and price assumptions.

Suggested script (10 min):
1. (1 min) Problem: hand-offs between dev and test.
2. (2 min) Run *Bug fix* at 2× speed. Pause when QA raises the regression — "this is the loop".
3. (2 min) Run *Stubborn defect*. Point at the escalation — "agents don't run forever; humans own the edge cases".
4. (2 min) Open the cost calculator; change iterations per item and model price live.
5. (3 min) Questions — keep `docs/09` open for security questions.

Controls: Space = play/pause, → = step, R = reset.

## B. Live demo on Azure (after Phase 2 of the roadmap)

Preparation (day before):
- Seed the sample app with a known bug (e.g. off-by-one in date filter) and a regression trap (a second test that a naive fix breaks).
- Pre-warm: run the pipelines once so agents and caches are warm.
- Have a backup recording of a full run.

Script (25 min):
1. Create the Bug live in Azure Boards with tag `ai-loop` (2 min).
2. Show the Orchestrator comment and tags appearing (1 min).
3. Show the dev-agent pipeline log while it works; open the PR when it lands (5 min).
4. Review and approve the PR as the human gate — read the agent's change summary aloud (3 min).
5. Show deploy-test, then the QA agent run and its child bug with Playwright trace (6 min).
6. Show iteration 2 updating the same PR, QA verdict, `ai-ready-for-signoff` (6 min).
7. Close with telemetry workbook: tokens, cost, time (2 min).

## Demo do's and don'ts

- Do show a failure path. A demo where everything passes first time is less convincing.
- Do show the human gates explicitly.
- Don't run against the client's real code in a first demo.
- Don't claim "fully autonomous" — claim "autonomous inside guardrails".
