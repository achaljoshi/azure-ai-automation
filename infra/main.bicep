// Starter infrastructure for the AI SDLC PoC. Foundry project + model deployments are created in the portal (docs/04).
@description('Short prefix for resource names')
param prefix string = 'aisdlc'
param location string = resourceGroup().location

@description('Azure DevOps organisation URL, e.g. https://dev.azure.com/contoso')
param adoOrgUrl string = ''
param adoProject string = ''
@description('Azure OpenAI / Foundry endpoint used by the triage model (and the agents, when LLM_PROVIDER=azure)')
param foundryEndpoint string = ''
param triageDeployment string = ''
param primaryDeployment string = ''
@description('Pipeline id of dev-agent.yml (set after you create the pipeline)')
param devAgentPipelineId int = 0
param qaAgentPipelineId int = 0
@description('Who gets assigned when the loop escalates (user principal name)')
param humanOwner string = ''
@description('azure | anthropic')
param llmProvider string = 'azure'
param iterationCap int = 3
param tokenBudget int = 2000000
param wallclockBudgetSeconds int = 14400

var suffix = uniqueString(resourceGroup().id)

resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${prefix}-law-${suffix}'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-appi-${suffix}'
  location: location
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: law.id }
}

resource st 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: toLower(take('${prefix}st${suffix}', 24))
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: { minimumTlsVersion: 'TLS1_2', allowBlobPublicAccess: false }
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take('${prefix}-kv-${suffix}', 24)
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}

resource orchestratorId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-id-orchestrator'
  location: location
}

// Function App (orchestrator) on a Linux consumption plan
resource funcPlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: '${prefix}-func-plan'
  location: location
  sku: { name: 'Y1', tier: 'Dynamic' }
  kind: 'functionapp'
  properties: { reserved: true }
}

resource func 'Microsoft.Web/sites@2023-01-01' = {
  name: '${prefix}-orchestrator-${suffix}'
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${orchestratorId.id}': {} } }
  properties: {
    serverFarmId: funcPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appSettings: [
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${st.name};AccountKey=${st.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString }
        { name: 'AZURE_CLIENT_ID', value: orchestratorId.properties.clientId }
        { name: 'ITERATION_CAP', value: string(iterationCap) }
        { name: 'TOKEN_BUDGET', value: string(tokenBudget) }
        { name: 'WALLCLOCK_BUDGET_S', value: string(wallclockBudgetSeconds) }
        { name: 'ADO_ORG_URL', value: adoOrgUrl }
        { name: 'ADO_PROJECT', value: adoProject }
        { name: 'FOUNDRY_ENDPOINT', value: foundryEndpoint }
        { name: 'TRIAGE_DEPLOYMENT', value: triageDeployment }
        { name: 'PRIMARY_DEPLOYMENT', value: primaryDeployment }
        { name: 'DEV_AGENT_PIPELINE_ID', value: string(devAgentPipelineId) }
        { name: 'QA_AGENT_PIPELINE_ID', value: string(qaAgentPipelineId) }
        { name: 'HUMAN_OWNER', value: humanOwner }
        { name: 'LLM_PROVIDER', value: llmProvider }
        { name: 'AGENT_IDENTITIES', value: '' }
        { name: 'KEY_VAULT_URI', value: kv.properties.vaultUri }
      ]
    }
  }
}

// Test environment for the system under test
resource webPlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: '${prefix}-test-plan'
  location: location
  sku: { name: 'B1', tier: 'Basic' }
  kind: 'linux'
  properties: { reserved: true }
}

resource testApp 'Microsoft.Web/sites@2023-01-01' = {
  name: '${prefix}-test-${suffix}'
  location: location
  properties: {
    serverFarmId: webPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'NODE|20-lts'
      appSettings: [ { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString } ]
    }
  }
}

resource loadTest 'Microsoft.LoadTestService/loadTests@2022-12-01' = {
  name: '${prefix}-lt-${suffix}'
  location: location
  properties: {}
}

output functionAppName string = func.name
output testWebAppName string = testApp.name
output testBaseUrl string = 'https://${testApp.properties.defaultHostName}'
output orchestratorPrincipalId string = orchestratorId.properties.principalId
output keyVaultName string = kv.name
