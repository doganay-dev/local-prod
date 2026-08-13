[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param()

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot

if (-not $PSCmdlet.ShouldProcess('gateway circuit breaker', 'Reset after the root cause has been resolved')) {
    return
}

$python = "import os,urllib.request; request=urllib.request.Request('http://127.0.0.1:8787/admin/circuit/reset', method='POST', headers={'X-Gateway-Admin-Token':os.environ['GATEWAY_ADMIN_TOKEN']}); print(urllib.request.urlopen(request, timeout=10).status)"

Push-Location $packageRoot
try {
    $statusCode = docker compose exec -T gateway python -c $python
    if ($LASTEXITCODE -ne 0 -or $statusCode -notcontains '204') {
        throw "Gateway circuit reset failed: $statusCode"
    }
}
finally {
    Pop-Location
}

Write-Host 'Gateway circuit reset (HTTP 204).'

