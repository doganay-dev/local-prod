[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param()

$ErrorActionPreference = 'Stop'
$taskName = 'Mockup Generator Local Prod'
$startScript = Join-Path $PSScriptRoot 'Start-LocalProd.ps1'
$powerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = 'PT1M'
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

if ($PSCmdlet.ShouldProcess($taskName, 'Create Windows startup task')) {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Starts the local n8n/gateway/PDF stack one minute after user logon.' -Force | Out-Null
    Write-Host "Installed scheduled task: $taskName"
}
