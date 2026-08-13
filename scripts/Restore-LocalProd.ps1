[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('n8n', 'gateway')]
    [string]$Component,

    [Parameter(Mandatory = $true)]
    [string]$Archive
)

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$resolvedArchive = (Resolve-Path -LiteralPath $Archive).Path
$volume = if ($Component -eq 'n8n') {
    'mockup_local_prod_n8n_data'
} else {
    'mockup_local_prod_gateway_data'
}
$archiveDirectory = Split-Path -Parent $resolvedArchive
$archiveName = Split-Path -Leaf $resolvedArchive

if (-not $PSCmdlet.ShouldProcess($volume, "Replace its contents from $resolvedArchive")) {
    return
}

Push-Location $packageRoot
try {
    docker compose stop n8n gateway
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop n8n and gateway safely' }

    # The named volume is explicit and validated by ValidateSet above. A temporary
    # Alpine container performs both removal and extraction in the same shell.
    docker run --rm --volume "${volume}:/target" --volume "${archiveDirectory}:/backup:ro" alpine:3.22 sh -c "find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar xzf '/backup/$archiveName' -C /target"
    if ($LASTEXITCODE -ne 0) { throw "Restore failed for $volume" }

    docker compose start gateway n8n
    if ($LASTEXITCODE -ne 0) { throw 'Could not restart gateway and n8n' }
}
finally {
    Pop-Location
}

Write-Host "Restored $Component from $resolvedArchive"
