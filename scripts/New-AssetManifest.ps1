[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DiffusionModel,
    [Parameter(Mandatory = $true)][string]$TextEncoder,
    [Parameter(Mandatory = $true)][string]$Vae,
    [string]$WorkflowConfig = (Join-Path (Split-Path -Parent $PSScriptRoot) 'gateway\config\workflow_config.json'),
    [string]$Output = (Join-Path (Split-Path -Parent $PSScriptRoot) 'asset-manifest.local.json')
)

$ErrorActionPreference = 'Stop'

function Get-AssetRecord {
    param([string]$Name, [string]$Path)

    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $file = Get-Item -LiteralPath $resolved
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $resolved
    return [ordered]@{
        name = $Name
        path = $resolved
        bytes = $file.Length
        sha256 = $hash.Hash.ToLowerInvariant()
    }
}

$manifest = [ordered]@{
    schema_version = 1
    created_at_utc = [DateTime]::UtcNow.ToString('o')
    assets = @(
        Get-AssetRecord 'diffusion_model' $DiffusionModel
        Get-AssetRecord 'text_encoder' $TextEncoder
        Get-AssetRecord 'vae' $Vae
        Get-AssetRecord 'gateway_workflow_config' $WorkflowConfig
    )
}

$resolvedOutput = [System.IO.Path]::GetFullPath($Output)
$parent = Split-Path -Parent $resolvedOutput
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $resolvedOutput -Encoding utf8
Write-Host "Wrote asset manifest: $resolvedOutput"

