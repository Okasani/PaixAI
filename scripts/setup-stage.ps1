[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$StageRoot = Join-Path $ProjectRoot 'stage'

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'Node.js 20 or newer is required for the optional Live2D stage.'
}

Push-Location $StageRoot
try {
    npm ci
}
finally {
    Pop-Location
}

Write-Host 'Live2D stage dependencies installed.' -ForegroundColor Green
Write-Host 'Run .\scripts\run-stage.ps1, then run .\scripts\run.ps1 -Stage in another terminal.'
