[CmdletBinding()]
param(
    [string]$ComfyBaseUrl = 'http://127.0.0.1:8188',
    [switch]$SkipComposeConfig
)

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$errors = [System.Collections.Generic.List[string]]::new()

function Add-CheckResult {
    param([string]$Label, [bool]$Ok, [string]$Detail)
    $marker = if ($Ok) { '[OK]' } else { '[HATA]' }
    Write-Host "$marker $Label - $Detail"
    if (-not $Ok) { $script:errors.Add("$Label`: $Detail") }
}

$docker = Get-Command docker -ErrorAction SilentlyContinue
Add-CheckResult 'Docker CLI' ($null -ne $docker) $(if ($docker) { $docker.Source } else { 'docker PATH icinde yok' })

if ($docker) {
    try {
        $serverVersion = docker info --format '{{.ServerVersion}}' 2>$null
        Add-CheckResult 'Docker Desktop Engine' ($LASTEXITCODE -eq 0) $serverVersion
    }
    catch {
        Add-CheckResult 'Docker Desktop Engine' $false $_.Exception.Message
    }
}

$envFile = Join-Path $packageRoot '.env'
Add-CheckResult '.env' (Test-Path -LiteralPath $envFile) $envFile
if (Test-Path -LiteralPath $envFile) {
    $envText = Get-Content -Raw -LiteralPath $envFile
    $values = @{}
    foreach ($line in ($envText -split "`r?`n")) {
        if ($line -match '^\s*([A-Z0-9_]+)=(.*)$') {
            $values[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
    $requiredKeys = @(
        'N8N_ENCRYPTION_KEY',
        'GATEWAY_ADMIN_TOKEN',
        'DRIVE_METAL_UNPRINTED_INPUT_ID',
        'DRIVE_METAL_PRINTED_INPUT_ID',
        'DRIVE_METAL_REVISION_UNPRINTED_INPUT_ID',
        'DRIVE_METAL_REVISION_PRINTED_INPUT_ID',
        'DRIVE_METAL_OUTPUT_ID',
        'DRIVE_METAL_DONE_ID',
        'DRIVE_METAL_REVISION_OUTPUT_ID',
        'DRIVE_METAL_REVISION_DONE_ID'
    )
    $unresolved = @($requiredKeys | Where-Object {
        (-not $values.ContainsKey($_)) -or
        [string]::IsNullOrWhiteSpace($values[$_]) -or
        $values[$_] -like 'replace-*'
    })
    Add-CheckResult '.env required values' ($unresolved.Count -eq 0) $(if ($unresolved.Count -eq 0) { 'all set' } else { $unresolved -join ', ' })
    if ($values.ContainsKey('N8N_ENCRYPTION_KEY')) {
        Add-CheckResult 'n8n encryption key length' ($values['N8N_ENCRYPTION_KEY'].Length -ge 32) 'minimum 32 characters'
    }
    if ($values.ContainsKey('GATEWAY_ADMIN_TOKEN')) {
        Add-CheckResult 'gateway admin token length' ($values['GATEWAY_ADMIN_TOKEN'].Length -ge 32) 'minimum 32 characters'
    }
}

$assetManifest = Join-Path $packageRoot 'asset-manifest.local.json'
Add-CheckResult 'Asset manifest' (Test-Path -LiteralPath $assetManifest) $assetManifest
if (Test-Path -LiteralPath $assetManifest) {
    try {
        & (Join-Path $PSScriptRoot 'Test-AssetManifest.ps1') -Manifest $assetManifest
        Add-CheckResult 'Pinned asset hashes' $true 'model, encoder, VAE and workflow config'
    }
    catch {
        Add-CheckResult 'Pinned asset hashes' $false $_.Exception.Message
    }
}

try {
    $stats = Invoke-RestMethod -Uri "$ComfyBaseUrl/system_stats" -TimeoutSec 10
    $deviceCount = @($stats.devices).Count
    Add-CheckResult 'ComfyUI API' $true "$ComfyBaseUrl; $deviceCount device(s)"
    $comfyVersionText = [string]$stats.system.comfyui_version
    $comfyVersion = $null
    $minimumVersion = [version]'0.28.0'
    if ([version]::TryParse(($comfyVersionText -replace '^v', ''), [ref]$comfyVersion)) {
        Add-CheckResult 'ComfyUI version' ($comfyVersion -ge $minimumVersion) $comfyVersionText
    }
    else {
        Add-CheckResult 'ComfyUI version' $false "unreadable version: $comfyVersionText"
    }
}
catch {
    Add-CheckResult 'ComfyUI API' $false $_.Exception.Message
}

if (-not $SkipComposeConfig -and $docker -and (Test-Path -LiteralPath $envFile)) {
    Push-Location $packageRoot
    try {
        $null = docker compose config --quiet 2>&1
        Add-CheckResult 'Compose config' ($LASTEXITCODE -eq 0) 'docker-compose.yml'
    }
    finally {
        Pop-Location
    }
}

if ($errors.Count -gt 0) {
    Write-Error ("Preflight failed:`n - " + ($errors -join "`n - "))
}

Write-Host '[OK] Preflight passed. This does not activate or import any workflow.'
