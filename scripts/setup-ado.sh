#!/usr/bin/env bash
# One-time Azure DevOps setup for the agent loop. Requires: az login, az extension add --name azure-devops
set -euo pipefail
: "${ADO_ORG:?set ADO_ORG=https://dev.azure.com/<org>}"
: "${ADO_PROJECT:?set ADO_PROJECT=<project>}"
FUNC_URL="${FUNC_URL:-https://<function-app>.azurewebsites.net/api/ado-events?code=<key>}"

az devops configure --defaults organization="$ADO_ORG" project="$ADO_PROJECT"

echo "Creating area path AI-Loop (ignore error if it exists)"
az boards area project create --name "AI-Loop" || true

echo "Creating variable group ai-agents"
az pipelines variable-group create --name ai-agents --authorize true --variables \
  FOUNDRY_ENDPOINT="https://<resource>.openai.azure.com/" \
  PRIMARY_DEPLOYMENT="<primary-model>" OPENAI_API_VERSION="2024-10-21" \
  TEST_BASE_URL="https://<test-webapp>.azurewebsites.net" \
  ORCHESTRATOR_URL="$FUNC_URL" QA_AGENT_PIPELINE_ID="0" TEST_WEBAPP_NAME="<test-webapp>" || true

cat <<MSG

Manual steps still required (see docs/04-setup-guide.md):
  1. Environments: create 'test' (no approvals) and 'prod' (manual approval, agents excluded).
  2. Branch policies on main: 1 human reviewer, build validation (ci.yml), linked work items, comment resolution.
  3. Deny 'Bypass policies when pushing/completing PRs' for agent identities.
  4. Service hooks (Web Hooks) -> $FUNC_URL
       - Work item created   (tag contains ai-loop)
       - Work item updated   (area path AI-Loop)
  5. Create pipelines from YAML: pipelines/ci.yml, deploy-test.yml, dev-agent.yml, qa-agent.yml
     then set DEV_AGENT_PIPELINE_ID (Function app setting) and QA_AGENT_PIPELINE_ID (variable group).

Tags used by the loop:
  ai-loop ai-owner:orchestrator ai-owner:dev ai-owner:qa ai-iter:N ai-needs-info
  ai-escalated ai-ready-for-signoff ai-raised ai-duplicate
MSG
