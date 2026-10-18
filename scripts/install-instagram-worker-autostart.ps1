$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskPython = Join-Path $taskRoot '.local/instagram-runtime/Scripts/pythonw.exe'
$taskScript = Join-Path $taskRoot 'scripts/zar-local-worker-service.py'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Falta el entorno local de Instagram.' }
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot '.local/instagram-worker/config.json'))) { throw 'Falta la conexión del worker con ZAR.' }
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskAction = New-ScheduledTaskAction -Execute $taskPython -Argument ('"' + $taskScript + '"') -WorkingDirectory $taskRoot
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'ZAR Local Instagram Worker' -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings -Description 'Worker exclusivo de Instagram ZAR. Sesión local y conexiones salientes; no requiere Codex.' -Force | Out-Null
Write-Output 'Autostart instalado para la sesión de Windows del usuario. No se guardan contraseñas.'
