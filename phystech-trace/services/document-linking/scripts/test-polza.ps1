$ErrorActionPreference = 'Stop'
$apiKey = [Environment]::GetEnvironmentVariable('POLZA_API_KEY', 'Process')
if (-not $apiKey) { $apiKey = [Environment]::GetEnvironmentVariable('POLZA_AI_API_KEY', 'Process') }
if (-not $apiKey) { $apiKey = [Environment]::GetEnvironmentVariable('POLZA_API_KEY', 'User') }
if (-not $apiKey) { $apiKey = [Environment]::GetEnvironmentVariable('POLZA_AI_API_KEY', 'User') }
if (-not $apiKey) {
  $envPath = Join-Path (Split-Path -Parent $PSScriptRoot) '.env'
  if (Test-Path -LiteralPath $envPath) {
    $keyLine = Get-Content -LiteralPath $envPath | Where-Object { $_ -match '^POLZA_API_KEY=' } | Select-Object -First 1
    if ($keyLine) { $apiKey = $keyLine.Substring('POLZA_API_KEY='.Length) }
  }
}
if (-not $apiKey) { throw 'Set POLZA_API_KEY or POLZA_AI_API_KEY in the Windows process or user environment.' }
$env:POLZA_API_KEY = $apiKey
& npx tsx --test tests/polza.integration.test.ts
exit $LASTEXITCODE
