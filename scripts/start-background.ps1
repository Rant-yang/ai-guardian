param([ValidateRange(1,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$dataDir = Join-Path $projectRoot '.local'
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
$url = "http://127.0.0.1:$Port"
function Test-Guardian {
    try {
        $tokenPath = Join-Path $dataDir 'access-token'
        if (-not (Test-Path -LiteralPath $tokenPath)) { return $false }
        $tokenValue = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
        $health = Invoke-RestMethod "$url/api/health" -Headers @{Authorization="Bearer $tokenValue"} -TimeoutSec 2
        $script:guardianHealth = $health
        return ($health.rules -eq 'ready' -and $health.service -eq 'agent-guardian' -and $health.api_version -eq 1)
    } catch { return $false }
}
# Serialize launches for this checkout. Separate checkouts must never reuse each other's credentials.
$hasher=[Security.Cryptography.SHA256]::Create()
try { $key=([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant())))).Replace('-','') }
finally { $hasher.Dispose() }
$mutex=New-Object Threading.Mutex($false,"Local\Guardian-Launch-$key-$Port")
$locked=$false
try {
    try { $locked=$mutex.WaitOne(15000) } catch [Threading.AbandonedMutexException] { $locked=$true }
    if(-not $locked) { throw 'Another Guardian launch is still running. Wait briefly and retry.' }
    if (Test-Guardian) {
        if($script:guardianHealth.status -eq 'stopping') { throw 'Guardian is draining accepted work. Wait for it to exit before starting again; no process was forced to stop.' }
        $runningRevision=$script:guardianHealth.backend_source_at_start
        if(-not $runningRevision) {
            Write-Warning 'Running Guardian has no backend revision evidence. Updates may require a restart after active actions and approvals finish. This launch did not restart it.'
        } else {
            try {
                . (Join-Path $PSScriptRoot 'runtime.ps1')
                $revisionPython=Get-GuardianPython -ProjectRoot $projectRoot
                $revisionScript=Join-Path $projectRoot 'guardian/runtime_revision.py'
                $diskRevision=(& $revisionPython $revisionScript).Trim()
                if($LASTEXITCODE -ne 0 -or $diskRevision -notmatch '^[0-9a-f]{64}$') { throw 'Revision unavailable' }
                if($diskRevision -ne $runningRevision) { Write-Warning 'Guardian backend source changed since startup. Finish active actions and approvals before restarting Guardian; this launch preserved the running service.' }
            } catch { Write-Warning 'Could not compare running Guardian with local source. No service was restarted.' }
        }
        Write-Output "Guardian already running: $url"; exit 0
    }
    $probe=New-Object Net.Sockets.TcpClient
    try {
        try { $probe.Connect('127.0.0.1',$Port);$occupied=$true } catch { $occupied=$false }
    } finally { $probe.Dispose() }
    if($occupied) { throw "Port $Port is occupied by a service that this checkout cannot authenticate. No process was stopped. Close the conflicting service or use its original Guardian folder." }
    . (Join-Path $PSScriptRoot 'runtime.ps1')
    $pythonExe = Get-GuardianPython -ProjectRoot $projectRoot
    $process = Start-Process -FilePath $pythonExe -ArgumentList @('-m','guardian.server','--port',"$Port") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataDir "server-$Port.log") -RedirectStandardError (Join-Path $dataDir "server-$Port.error.log") -PassThru
    $null=$process.Handle
    for ($attempt=0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        $process.Refresh()
        if ($process.HasExited) { break }
        if (Test-Guardian) {
            $serviceProcess=$null
            try {
                # Windows venv python.exe may be a launcher whose child owns HTTP.
                # Trust the authenticated health identity only after checking ancestry.
                $servicePid=[int]$script:guardianHealth.process_id
                $serviceRecord=Get-CimInstance Win32_Process -Filter "ProcessId=$servicePid"
                if(-not $serviceRecord -or $serviceRecord.Name -notmatch '^python(w)?\.exe$' -or $serviceRecord.CommandLine -notmatch "-m guardian\.server --port $Port(\s|$)" -or ($servicePid -ne $process.Id -and $serviceRecord.ParentProcessId -ne $process.Id)) {
                    throw 'Authenticated service is not the launched Python process or its direct child.'
                }
                $serviceProcess=[Diagnostics.Process]::GetProcessById($servicePid)
                $null=$serviceProcess.Handle
                $identity=@{schema=1;pid=$servicePid;started_utc_ticks=$serviceProcess.StartTime.ToUniversalTime().Ticks.ToString();project_root=$projectRoot;executable=$serviceRecord.ExecutablePath;launcher_pid=$process.Id}
                $identity | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $dataDir "server-$Port.identity.json")
                $servicePid | Set-Content -LiteralPath (Join-Path $dataDir "server-$Port.pid")
            } catch {
                if($serviceProcess) {
                    $serviceProcess.Refresh()
                    if(-not $serviceProcess.HasExited) { $serviceProcess.Kill();$serviceProcess.WaitForExit() }
                }
                $process.Refresh()
                if(-not $process.HasExited) { $process.Kill();$process.WaitForExit() }
                throw 'Guardian launch records could not be saved. The newly launched process was stopped. Check permissions in .local and retry; no other process was stopped.'
            }
            Write-Output "Guardian running independently (PID $servicePid): $url"
            exit 0
        }
    }
    $process.Refresh()
    if(-not $process.HasExited) { $process.Kill();$process.WaitForExit() }
    throw "Guardian did not become ready. Check .local/server-$Port.error.log. The unsuccessful launch was stopped; existing PID records were preserved."
} finally {
    if($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
