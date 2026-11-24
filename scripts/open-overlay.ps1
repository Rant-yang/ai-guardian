$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'start-background.ps1')
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
. (Join-Path $PSScriptRoot 'runtime.ps1')
$pythonExe=Get-GuardianPython -ProjectRoot $projectRoot
Start-Process -FilePath $pythonExe -ArgumentList @('-m','guardian.desktop') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectRoot '.local/desktop.log') -RedirectStandardError (Join-Path $projectRoot '.local/desktop.error.log')
