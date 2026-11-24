param([int]$Port = 8765,[switch]$Force)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pidFile = Join-Path $projectRoot ".local/server-$Port.pid"
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'No recorded Guardian process.'; exit 0 }
$guardianPid = [int](Get-Content -LiteralPath $pidFile -Raw)
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$guardianPid"
if (-not $process) { Write-Output 'Guardian already stopped.'; exit 0 }
if ($process.Name -notmatch '^python(w)?\.exe$' -or $process.CommandLine -notmatch "-m guardian\.server --port $Port(\s|$)") { throw 'Recorded PID no longer belongs to the expected Guardian command; refusing to stop it.' }
$identityFile=Join-Path $projectRoot ".local/server-$Port.identity.json"
if(-not (Test-Path -LiteralPath $identityFile -PathType Leaf)) { throw 'No verified launch identity exists for this legacy process. Refusing automatic stop; confirm and close the original Guardian process manually.' }
$identity=Get-Content -LiteralPath $identityFile -Raw -Encoding UTF8 | ConvertFrom-Json
if($identity.schema -ne 1 -or $identity.pid -ne $guardianPid -or $identity.project_root -ne $projectRoot -or $identity.executable -ne $process.ExecutablePath) { throw 'Guardian launch identity does not match this checkout; refusing to stop it.' }
$owned=[Diagnostics.Process]::GetProcessById($guardianPid)
try {
    # Pin a process handle before verifying creation time so a recycled PID is not killed.
    $null=$owned.Handle
    if($owned.StartTime.ToUniversalTime().Ticks.ToString() -ne $identity.started_utc_ticks) { throw 'Guardian process creation time changed; refusing to stop it.' }
    if($Force) {
        $owned.Kill()
        $owned.WaitForExit()
    } else {
        $adminPath=Join-Path $projectRoot '.local/admin-token'
        if(-not (Test-Path -LiteralPath $adminPath -PathType Leaf)) { throw 'Management credential unavailable; no process stopped. Use -Force only after checking active work.' }
        $adminToken=(Get-Content -LiteralPath $adminPath -Raw).Trim()
        $headers=@{Authorization="Bearer $adminToken"}
        $health=Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -Headers $headers -TimeoutSec 3
        if($health.process_id -ne $guardianPid -or $health.graceful_shutdown -ne $true) { throw 'Running service cannot confirm graceful shutdown identity. No process stopped; use -Force only after checking active work.' }
        $body=@{confirmed=$true;expected_pid=$guardianPid} | ConvertTo-Json -Compress
        $result=Invoke-RestMethod "http://127.0.0.1:$Port/api/service/shutdown" -Method Post -Headers $headers -ContentType 'application/json' -Body $body -TimeoutSec 3
        if($result.stopping -ne $true -or $result.process_id -ne $guardianPid) { throw 'Shutdown was not acknowledged; no forced stop attempted.' }
        if(-not $owned.WaitForExit(20000)) { throw 'Guardian is still draining accepted work. No forced stop attempted; wait and inspect active work before using -Force.' }
    }
} finally { $owned.Dispose() }
Write-Output "Guardian stopped (PID $guardianPid)."
