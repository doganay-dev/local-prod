[CmdletBinding()]
param(
    [string]$Destination = (Join-Path (Split-Path -Parent $PSScriptRoot) 'backups')
)

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$resolvedDestination = [System.IO.Path]::GetFullPath($Destination)
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'

New-Item -ItemType Directory -Force -Path $resolvedDestination | Out-Null

Push-Location $packageRoot
try {
    docker compose stop n8n gateway
    if ($LASTEXITCODE -ne 0) { throw 'Services could not be stopped for a consistent backup' }

    $volumes = @(
        @{ Name = 'mockup_local_prod_n8n_data'; File = "n8n-data-$timestamp.tar.gz" },
        @{ Name = 'mockup_local_prod_gateway_data'; File = "gateway-data-$timestamp.tar.gz" }
    )
    foreach ($volume in $volumes) {
        $null = docker volume inspect $volume.Name 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Volume does not exist: $($volume.Name)" }
        $archivePath = Join-Path $resolvedDestination $volume.File
        docker run --rm --volume "$($volume.Name):/source:ro" --volume "${resolvedDestination}:/backup" alpine:3.22 tar czf "/backup/$($volume.File)" -C /source .
        if ($LASTEXITCODE -ne 0) { throw "Backup failed: $($volume.Name)" }
        Write-Host "Created $archivePath"
    }
}
finally {
    docker compose start gateway n8n | Out-Host
    Pop-Location
}
