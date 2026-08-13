[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param()

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$ruleName = 'Mockup Generator - ComfyUI from Docker only'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an elevated PowerShell window.'
}

Push-Location $packageRoot
try {
    # Creates the Compose network but does not start n8n or activate a workflow.
    docker compose create
    if ($LASTEXITCODE -ne 0) { throw 'docker compose create failed' }

    $subnet = docker network inspect mockup_local_prod_internal --format '{{(index .IPAM.Config 0).Subnet}}'
    if ($LASTEXITCODE -ne 0 -or $subnet -notmatch '^(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}$') {
        throw "Could not determine the Compose subnet: $subnet"
    }
}
finally {
    Pop-Location
}

if ($PSCmdlet.ShouldProcess("TCP 8188 from $subnet", "Replace firewall rule '$ruleName'")) {
    Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Description 'Allow only the Mockup Generator Docker subnet to call native ComfyUI.' `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort 8188 `
        -RemoteAddress $subnet `
        -Profile Any | Out-Null
    Write-Host "Allowed ComfyUI TCP 8188 only from Compose subnet $subnet."
}

Write-Warning 'Audit and disable any pre-existing broad inbound Python/ComfyUI/8188 allow rules; a broad rule would defeat this scope.'

