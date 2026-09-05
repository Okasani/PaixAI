param([string]$Assets = '', [int]$Port = 5000)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Assets) { $Assets = Join-Path $projectRoot 'config/voice-assets.json' }
$Assets = (Resolve-Path -LiteralPath $Assets).Path
$ttsPython = Join-Path $projectRoot '.venv-tts/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $ttsPython)) { throw 'Run scripts/setup-local-tts.ps1 first.' }
Push-Location (Join-Path $projectRoot 'backend')
try {
    & $ttsPython -m app.providers.tts.bridge --assets $Assets --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Local TTS bridge stopped with an error.' }
} finally { Pop-Location }
