[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$JobId
)

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot

if (-not $PSCmdlet.ShouldProcess("gateway job $JobId", 'Delete its failed record and spool output for a deliberate rerender')) {
    return
}

$python = "import os,urllib.request; job_id=os.environ['RESET_JOB_ID']; request=urllib.request.Request('http://127.0.0.1:8787/admin/jobs/'+job_id+'/reset', method='POST', headers={'X-Gateway-Admin-Token':os.environ['GATEWAY_ADMIN_TOKEN']}); print(urllib.request.urlopen(request, timeout=10).status)"

Push-Location $packageRoot
try {
    $statusCode = docker compose exec -T -e "RESET_JOB_ID=$JobId" gateway python -c $python
    if ($LASTEXITCODE -ne 0 -or $statusCode -notcontains '204') {
        throw "Gateway job reset failed: $statusCode"
    }
}
finally {
    Pop-Location
}

Write-Host "Gateway job reset: $JobId (HTTP 204)."

