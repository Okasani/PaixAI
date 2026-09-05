[CmdletBinding()]
param(
    [string]$ModelKey = 'qwen/qwen3.5-4b',
    [string]$ModelSpec = 'qwen/qwen3.5-4b@q4_k_m',
    [string]$Identifier = 'paix-local',
    [int]$Port = 1234,
    [int]$ContextLength = 8192
)

$ErrorActionPreference = 'Stop'
$LmsCommand = Get-Command lms -ErrorAction SilentlyContinue
if (-not $LmsCommand) {
    throw 'LM Studio CLI (lms) is required. Install LM Studio, then run: npx lmstudio install-cli'
}

$InstalledModels = @(& $LmsCommand.Source ls --json | ConvertFrom-Json)
$ModelInstalled = $InstalledModels | Where-Object { $_.modelKey -eq $ModelKey }
if (-not $ModelInstalled) {
    Write-Host "Downloading the local Paix model ($ModelSpec)..." -ForegroundColor Cyan
    & $LmsCommand.Source get $ModelSpec --gguf -y
    if ($LASTEXITCODE -ne 0) { throw "Failed to download local model: $ModelSpec" }
}

$ServerStatus = & $LmsCommand.Source server status --json | ConvertFrom-Json
if (-not $ServerStatus.running) {
    Write-Host "Starting LM Studio on 127.0.0.1:$Port..." -ForegroundColor Cyan
    & $LmsCommand.Source server start --port $Port --bind 127.0.0.1
    if ($LASTEXITCODE -ne 0) { throw 'Failed to start the local LM Studio server.' }
}
elseif ($ServerStatus.port -ne $Port) {
    throw "LM Studio is already running on port $($ServerStatus.port), but Paix expects port $Port."
}

$LoadedModels = @(& $LmsCommand.Source ps --json | ConvertFrom-Json)
$PaixModel = $LoadedModels | Where-Object {
    $_.identifier -eq $Identifier -or $_.modelKey -eq $Identifier
}
if (-not $PaixModel) {
    Write-Host "Loading $ModelKey into GPU memory as '$Identifier'..." -ForegroundColor Cyan
    & $LmsCommand.Source load $ModelKey --gpu max --context-length $ContextLength --parallel 1 --identifier $Identifier -y
    if ($LASTEXITCODE -ne 0) { throw "Failed to load local model: $ModelKey" }
}

Write-Host "Local Paix model is ready at http://127.0.0.1:$Port/v1" -ForegroundColor Green
