[CmdletBinding()]
param([switch]$SkipPreflight)

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot

if (-not $SkipPreflight) {
    & (Join-Path $PSScriptRoot 'Preflight.ps1')
}

Push-Location $packageRoot
try {
    docker compose up --detach --build
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }
    docker compose ps
}
finally {
    Pop-Location
}

Write-Host 'n8n: http://127.0.0.1:5678'
Write-Host 'No workflow is activated automatically.'

