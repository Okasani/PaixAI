[CmdletBinding()]
param(
    [switch]$TypedOnly
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BackendRoot = Join-Path $ProjectRoot 'backend'
$EnvironmentFile = Join-Path $ProjectRoot '.env'
$EnvironmentExample = Join-Path $ProjectRoot '.env.example'

Write-Host 'Setting up Paix with Python 3.11...'

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is required. Install it from https://docs.astral.sh/uv/ or run: winget install --id=astral-sh.uv -e'
}

uv python install 3.11

Push-Location $BackendRoot
try {
    $SyncArguments = @('sync', '--python', '3.11', '--extra', 'dev')
    if (-not $TypedOnly) {
        $SyncArguments += @('--extra', 'speech')
    }
    & uv @SyncArguments
}
finally {
    Pop-Location
}

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot 'data') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot '.secrets') | Out-Null

if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    Copy-Item -LiteralPath $EnvironmentExample -Destination $EnvironmentFile
    Write-Host 'Created .env from safe placeholders.'
}

Write-Host ''
Write-Host 'Setup complete.' -ForegroundColor Green
Write-Host 'Open paix.code-workspace in VS Code and press F5 using "Voice: Paix (Local Qwen)".'
Write-Host 'Or run: .\scripts\run.ps1'
