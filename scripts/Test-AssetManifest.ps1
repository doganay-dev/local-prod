[CmdletBinding()]
param(
    [string]$Manifest = (Join-Path (Split-Path -Parent $PSScriptRoot) 'asset-manifest.local.json')
)

$ErrorActionPreference = 'Stop'
$resolvedManifest = (Resolve-Path -LiteralPath $Manifest).Path
$data = Get-Content -Raw -LiteralPath $resolvedManifest | ConvertFrom-Json

if ($data.schema_version -ne 1 -or @($data.assets).Count -ne 4) {
    throw 'Asset manifest schema or asset count is invalid.'
}

$failures = [System.Collections.Generic.List[string]]::new()
foreach ($asset in $data.assets) {
    if (-not (Test-Path -LiteralPath $asset.path -PathType Leaf)) {
        $failures.Add("$($asset.name): file missing")
        continue
    }
    $file = Get-Item -LiteralPath $asset.path
    if ($file.Length -ne [long]$asset.bytes) {
        $failures.Add("$($asset.name): size changed")
        continue
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $asset.path).Hash.ToLowerInvariant()
    if ($actual -ne [string]$asset.sha256) {
        $failures.Add("$($asset.name): SHA-256 changed")
    }
    else {
        Write-Host "[OK] $($asset.name)"
    }
}

if ($failures.Count -gt 0) {
    throw ("Asset verification failed:`n - " + ($failures -join "`n - "))
}

Write-Host '[OK] Pinned model and workflow assets match the manifest.'

