$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
try {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv-tts'
    & uv sync --project (Join-Path $projectRoot 'backend') --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Local TTS environment setup failed.' }
    $ttsPython = Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts/python.exe'
    & uv pip install --python $ttsPython 'style-bert-vits2 @ git+https://github.com/litagin02/Style-Bert-VITS2.git@66de777e06392c0f313600be03c43ef96658b244'
    if ($LASTEXITCODE -ne 0) { throw 'Style-Bert-VITS2 installation failed.' }
    Write-Host 'TTS libraries installed separately. Configure licensed voice assets and local BERT resources before starting.'
} finally { $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment }
