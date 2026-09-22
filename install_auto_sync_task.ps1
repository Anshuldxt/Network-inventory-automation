$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python -ErrorAction Stop).Source
$syncScript = Join-Path $scriptDir "auto_sync.py"
$taskName = "MultiVendorSiteSearch-DailySync"
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$syncScript`" --sync-now" -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -Daily -At 10:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Installed $taskName for daily 10:00 local time."
Write-Host "The task runs only when this Windows user is logged on and Outlook is available."
Write-Host "Run now: Start-ScheduledTask -TaskName $taskName"
