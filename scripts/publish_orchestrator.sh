#!/usr/bin/env bash
# Publish the orchestrator Function App. Copies the triage prompt into the package first (the Function deploys only orchestrator/).
# usage: bash scripts/publish_orchestrator.sh <function-app-name>
set -euo pipefail
APP="${1:?usage: publish_orchestrator.sh <function-app-name>}"
cd "$(dirname "$0")/../orchestrator"
mkdir -p prompts
cp ../agents/prompts/orchestrator.md prompts/orchestrator.md
func azure functionapp publish "$APP" --python --build remote
