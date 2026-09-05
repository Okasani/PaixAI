param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend')
try {
    & uv run python -m app.diagnostics.cli @Arguments
    exit $LASTEXITCODE
} finally { Pop-Location }
