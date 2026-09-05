[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$StageRoot = Join-Path $ProjectRoot 'stage'

if (-not (Test-Path -LiteralPath (Join-Path $StageRoot 'node_modules'))) {
    throw 'Live2D stage dependencies are missing. Run .\scripts\setup-stage.ps1 first.'
}

Push-Location $StageRoot
try {
    npm run start
}
finally {
    Pop-Location
}
