[CmdletBinding()]
param(
    [string]$Provider = 'local',
    [string]$Model = '',
    [string]$VoiceId = '',
    [string]$ConversationId = 'voice-primary',
    [string]$InputDevice = '',
    [string]$OutputDevice = '',
    [switch]$TypedOnly,
    [switch]$PushToTalk,
    [switch]$Stage,
    [switch]$NoTts,
    [switch]$SkipLocalModelStart,
    [switch]$ListDevices,
    [switch]$ListVoices
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BackendRoot = Join-Path $ProjectRoot 'backend'
$PythonPath = Join-Path $BackendRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw 'Backend environment not found. Run .\scripts\setup.ps1 first.'
}

if ($Provider -eq 'local' -and -not $SkipLocalModelStart) {
    & (Join-Path $PSScriptRoot 'start-local-model.ps1')
}

$VoiceArguments = @('-m', 'app.voice.cli', '--conversation-id', $ConversationId)
$VoiceArguments += @('--provider', $Provider)
if ($Model) { $VoiceArguments += @('--model', $Model) }
if ($VoiceId) { $VoiceArguments += @('--voice-id', $VoiceId) }
if ($InputDevice) { $VoiceArguments += @('--input-device', $InputDevice) }
if ($OutputDevice) { $VoiceArguments += @('--output-device', $OutputDevice) }
if ($TypedOnly) { $VoiceArguments += '--typed-only' }
if ($PushToTalk) { $VoiceArguments += '--push-to-talk' }
if ($Stage) { $VoiceArguments += '--stage' }
if ($NoTts) { $VoiceArguments += '--no-tts' }
if ($ListDevices) { $VoiceArguments += '--list-devices' }
if ($ListVoices) { $VoiceArguments += '--list-voices' }

Push-Location $BackendRoot
try {
    & $PythonPath @VoiceArguments
}
finally {
    Pop-Location
}
