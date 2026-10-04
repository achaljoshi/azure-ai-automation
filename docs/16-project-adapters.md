# 16 — Project adapters: pointing the loop at a repository

The loop is generic. Everything project-specific lives in one file in the **target** repository: `.agent/project.json`. It tells the agents and the trusted gates how to install, build and test, where QA may write, and what is off limits.

```json
{
  "name": "html-reporting",
  "install": "npm ci",
  "build": "npm run build",
  "unit_test": "npm test",
  "e2e_test": "npm run test:e2e",
  "serve": "npm run serve",
  "base_url": "http://localhost:8765",
  "qa_write_dir": "tests/ai-generated/",
  "allowed_cmds": ["npm run", "npm test", "node --test", "npx playwright test", "git status", "git diff"],
  "protected_paths": ["templates/", "samples/", "assets/lib/", ".github/"],
  "diff_budget": { "files": 15, "lines": 600 },
  "agent_instructions": "AGENTS.md",
  "definition_of_done": ["npm run build", "npm test", "npm run test:e2e"]
}
```

| Field | Meaning |
|---|---|
| `install`, `build`, `unit_test`, `e2e_test` | Commands run by the **trusted gates** (outside the agent) after every dev and QA step. Empty = skipped. |
| `allowed_cmds` | The only commands the agent can run, matched by leading tokens (`"npm run"` allows `npm run build`, not `npm install`). No shell operators. |
| `protected_paths` | Added to the built-in defaults, which always apply: `pipelines/`, `infra/`, `.azuredevops/`, `.github/`, `.git/`, `.agent/`, `qa-thresholds.json`, `tests/quarantine.txt`, `package.json`, lock files, `requirements*.txt`, `pyproject.toml`. |
| `qa_write_dir` | The QA agent can write only here (one sub-folder per work item). |
| `diff_budget` | Files / changed lines the Development agent may touch before the run is stopped. |
| `agent_instructions` | A file in the repo (e.g. `AGENTS.md`) appended to the agent prompts: architecture, conventions, definition of done. It is data about how to work there; it cannot lift the sandbox rules. |

## Adding a project

1. Add `.agent/project.json` and an `AGENTS.md` to the target repo; make `build`, `unit_test`, `e2e_test` real commands that exit non-zero on failure.
2. Run locally first: `python agents/local_loop.py --repo <path> --task "..."`.
3. For Azure DevOps: copy `pipelines/` into the target repo, add this repo as the `agentkit` repository resource, create the four pipelines ([docs/04](04-setup-guide.md)).

## Example: the ATS dashboard (`html-reporting`)

A no-server HTML dashboard (plain browser JavaScript, Excel in, PDF/PowerPoint out). Its adapter uses Node's built-in test runner for unit tests and Playwright (headless Chromium, the app's own `tools/qa_harness.js` sweep) for end-to-end tests. Templates, sample data, bundled libraries and the PowerPoint theme are protected because they carry client branding and fictional data that humans curate.

### Verified run (scripted agents, real project)

Against a copy of the dashboard with a deliberately re-introduced bug (month-first dates such as `9/25/2026` rejected), `local_loop.py` produced: iteration 1 — the dev agent's attempts to edit a bundled library, `package.json` and to run `npm install` were all **denied** by the sandbox, it claimed success without fixing anything, and the trusted gates failed (1 unit test, e2e spec) → two child bugs; iteration 2 — the real fix in `assets/js/core.js`, gates green, QA verdict pass, status `ready_for_signoff`. The branch held exactly two changed files (the fix and the QA agent's Playwright spec). The scripted agents stand in for a real model; with `LLM_PROVIDER` set, the same loop runs with Claude or Azure OpenAI.
