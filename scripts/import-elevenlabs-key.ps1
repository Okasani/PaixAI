[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceKeyFile,
    [switch]$DeleteSource
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$SecretsDirectory = Join-Path $ProjectRoot '.secrets'
$DestinationKeyFile = Join-Path $SecretsDirectory 'elevenlabs.key'
$EnvironmentFile = Join-Path $ProjectRoot '.env'
$EnvironmentExample = Join-Path $ProjectRoot '.env.example'

$ResolvedSource = (Resolve-Path -LiteralPath $SourceKeyFile).Path
$SourceMetadata = Get-Item -LiteralPath $ResolvedSource
if ($SourceMetadata.PSIsContainer) {
    throw 'The source must be a file.'
}
if ($SourceMetadata.Length -lt 16 -or $SourceMetadata.Length -gt 4096) {
    throw 'The source file size is not plausible for a single API key.'
}

New-Item -ItemType Directory -Force -Path $SecretsDirectory | Out-Null
Copy-Item -LiteralPath $ResolvedSource -Destination $DestinationKeyFile -Force

$DestinationMetadata = Get-Item -LiteralPath $DestinationKeyFile
if ($DestinationMetadata.Length -ne $SourceMetadata.Length) {
    throw 'The secret transfer could not be verified by file size. The source was preserved.'
}

if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    Copy-Item -LiteralPath $EnvironmentExample -Destination $EnvironmentFile
}

if ($DeleteSource) {
    Remove-Item -LiteralPath $ResolvedSource -Force
    Write-Host 'ElevenLabs key transferred to the git-ignored server secret file; the source file was deleted.' -ForegroundColor Green
}
else {
    Write-Host 'ElevenLabs key transferred to the git-ignored server secret file; the source file was preserved.' -ForegroundColor Green
}

Write-Host 'The key contents were not printed or placed in client code.'
