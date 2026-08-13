[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot

Push-Location $packageRoot
try {
    docker compose stop
    if ($LASTEXITCODE -ne 0) { throw 'docker compose stop failed' }
}
finally {
    Pop-Location
}

