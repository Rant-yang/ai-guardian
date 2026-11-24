$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
try {
  $health=Invoke-RestMethod 'http://127.0.0.1:18765/health' -TimeoutSec 2
  if($health.service -ne 'guardian-showcase'){throw 'Port belongs to another service.'}
  Write-Output 'Showcase service already running.'
  exit 0
} catch {
  if($_.Exception.Message -eq 'Port belongs to another service.'){throw}
}
$pythonExe=(Get-Command python.exe).Source
$dataDir=Join-Path $projectRoot '.local'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$process=Start-Process $pythonExe -ArgumentList @('-m','demos.agent-showcase.local_service') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataDir 'showcase-service.log') -RedirectStandardError (Join-Path $dataDir 'showcase-service.error.log')
$process.Id | Set-Content (Join-Path $dataDir 'showcase-service.pid')
Start-Sleep -Milliseconds 800
$health=Invoke-RestMethod 'http://127.0.0.1:18765/health' -TimeoutSec 3
if($health.service -ne 'guardian-showcase'){throw 'Unexpected service identity.'}
