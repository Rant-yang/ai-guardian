$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$pidFile=Join-Path $projectRoot '.local/showcase-service.pid'
if(-not (Test-Path -LiteralPath $pidFile)){exit 0}
$fixturePid=[int](Get-Content -LiteralPath $pidFile -Raw)
$process=Get-CimInstance Win32_Process -Filter "ProcessId=$fixturePid"
if(-not $process){exit 0}
if($process.Name -notmatch '^python(w)?\.exe$' -or $process.CommandLine -notmatch '\s-m\s+demos\.agent-showcase\.local_service(?:\s|$)'){throw 'PID no longer belongs to showcase service.'}
Stop-Process -Id $fixturePid
