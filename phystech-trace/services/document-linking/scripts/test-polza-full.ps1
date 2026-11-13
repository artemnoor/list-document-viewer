$ErrorActionPreference = 'Stop'
$env:POLZA_RUN_FULL_SET = 'true'
& (Join-Path $PSScriptRoot 'test-polza.ps1')
exit $LASTEXITCODE
