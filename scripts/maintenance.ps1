param([ValidateSet('check','disconnect','report')][string]$Action='check')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    . (Join-Path $PSScriptRoot 'runtime.ps1')
    $pythonExe=Get-GuardianPython -ProjectRoot $projectRoot -AllowRepair
    $env:PYTHONIOENCODING='utf-8'
    [Console]::OutputEncoding=New-Object System.Text.UTF8Encoding
    & $pythonExe -m guardian.maintenance $Action
    if($LASTEXITCODE -ne 0) { throw 'Maintenance did not complete. Keep the project directory and review the messages above.' }
} finally { Pop-Location }
