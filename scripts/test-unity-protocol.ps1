$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sources = @(
    (Join-Path $projectRoot 'unity/Assets/Paix/AvatarProtocol.cs'),
    (Join-Path $projectRoot 'unity/Assets/Paix/AvatarController.cs'),
    (Join-Path $projectRoot 'unity/Tests/ProtocolTests.cs')
)
$references = @((Get-ChildItem -LiteralPath (Join-Path $PSHOME 'ref') -Filter '*.dll').FullName)
$references += [Newtonsoft.Json.JsonConvert].Assembly.Location
Add-Type -Path $sources -ReferencedAssemblies $references -CompilerOptions /nowarn:1701
[ProtocolTests]::Run()

