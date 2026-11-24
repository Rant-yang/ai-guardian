param(
    [ValidateRange(5,3600)][int]$Seconds = 60,
    [ValidateRange(1,30)][int]$Interval = 2,
    [string]$Output = (Join-Path $PSScriptRoot '../.local/desktop-resources.json')
)
$ErrorActionPreference = 'Stop'
# Read-only measurement. Never persist command lines, window titles or other apps.
$rows = @(Get-CimInstance Win32_Process)
$roots = @($rows | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and
    $_.CommandLine -match '\s-m\s+guardian\.desktop(?:\s|$)'
})
if ($roots.Count -ne 1) { throw 'Expected exactly one running Guardian desktop; no measurement started.' }
$rootPid = [int]$roots[0].ProcessId
$rootCreated = $roots[0].CreationDate
$samples = [Collections.Generic.List[object]]::new()
$previous = @{}
$timer = [Diagnostics.Stopwatch]::StartNew()
$lastTime = 0.0
$logicalCpus = [Environment]::ProcessorCount
$interrupted = $false
while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
    $rows = @(Get-CimInstance Win32_Process)
    $anchor = @($rows | Where-Object { $_.ProcessId -eq $rootPid -and $_.CreationDate -eq $rootCreated })
    if ($anchor.Count -ne 1) { $interrupted = $true; break }
    $selected = @{}; $selected[$rootPid] = $anchor[0]
    do {
        $added = $false
        foreach ($row in $rows) {
            $parent = $selected[[int]$row.ParentProcessId]
            if ($parent -and -not $selected.ContainsKey([int]$row.ProcessId) -and $row.CreationDate -ge $parent.CreationDate) {
                $selected[[int]$row.ProcessId] = $row; $added = $true
            }
        }
    } while ($added)
    $now = $timer.Elapsed.TotalSeconds
    $current = @{}; $cpuDelta = 0.0; $workingSet = 0.0; $handles = 0; $newCount = 0
    $privateBytes=0.0; $privateComplete=$true; $processDetails=[Collections.Generic.List[object]]::new()
    foreach ($row in $selected.Values) {
        $identity = "$($row.ProcessId):$($row.CreationDate.ToUniversalTime().Ticks)"
        $cpu = ([double]$row.KernelModeTime + [double]$row.UserModeTime) / 10000000
        $current[$identity] = $cpu
        if ($previous.ContainsKey($identity)) { $cpuDelta += [Math]::Max(0, $cpu - $previous[$identity]) }
        else { $newCount++ }
        $workingSet += [double]$row.WorkingSetSize
        $handles += [int]$row.HandleCount
        $privateMiB=$null
        try {
            $live=Get-Process -Id ([int]$row.ProcessId) -ErrorAction Stop
            try {
                # CIM timestamps have microsecond precision; do not pair a reused PID.
                if($live.StartTime.ToUniversalTime().ToString('yyyyMMddHHmmssffffff') -ne $row.CreationDate.ToUniversalTime().ToString('yyyyMMddHHmmssffffff')) { throw 'Process identity changed' }
                $bytes=[double]$live.PrivateMemorySize64
                $privateBytes+=$bytes;$privateMiB=[Math]::Round($bytes/1MB,2)
            } finally { $live.Dispose() }
        } catch { $privateComplete=$false }
        $role='other-child'
        if([int]$row.ProcessId -eq $rootPid) { $role='desktop-host' }
        elseif($row.Name -eq 'msedgewebview2.exe') {
            $role='webview-browser'
            if($row.CommandLine -match '--type=(renderer|gpu-process|utility|crashpad-handler)(?:\s|$)') { $role='webview-'+$Matches[1] }
        }
        $processDetails.Add([ordered]@{pid=[int]$row.ProcessId;role=$role;working_set_mib=[Math]::Round([double]$row.WorkingSetSize/1MB,2);private_committed_mib=$privateMiB;handles=[int]$row.HandleCount})
    }
    $departed = @($previous.Keys | Where-Object { -not $current.ContainsKey($_) }).Count
    $cpuPercent = $null
    if ($samples.Count -gt 0) { $cpuPercent = [Math]::Round(100 * $cpuDelta / ($now - $lastTime) / $logicalCpus, 3) }
    $samples.Add([ordered]@{
        elapsed_seconds = [Math]::Round($now,3); process_count = $selected.Count
        cpu_machine_percent = $cpuPercent; working_set_sum_mib = [Math]::Round($workingSet/1MB,2)
        handles = $handles; new_processes = $newCount; departed_processes = $departed
        private_committed_sum_mib = $(if($privateComplete){[Math]::Round($privateBytes/1MB,2)}else{$null})
        private_measurement_complete = $privateComplete; processes = @($processDetails.ToArray())
    })
    $previous = $current; $lastTime = $now
    Start-Sleep -Milliseconds ([int][Math]::Max(0,[Math]::Min($Interval*1000,($Seconds-$timer.Elapsed.TotalSeconds)*1000)))
}
$result = [ordered]@{
    status = $(if ($interrupted) {'desktop_exited'} else {'completed'})
    root_pid = $rootPid; logical_cpus = $logicalCpus; requested_seconds = $Seconds
    elapsed_seconds = [Math]::Round($timer.Elapsed.TotalSeconds,2)
    scope = 'Existing Guardian desktop and descendants; read-only CIM sampling'
    limitations = @('Not GPU, frame-rate or visual-quality measurement',
        'Working-set sum may double-count shared pages',
        'Private committed memory is not private resident RAM; null means incomplete identity-checked measurement',
        'CPU excludes processes born or exited between samples; inspect churn counters',
        'Other applications and sampling overhead are not controlled; not a release threshold')
    samples = @($samples.ToArray())
}
$destination = [IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $destination -Encoding utf8
Write-Output "Desktop resource report: $destination ($($result.status), $($samples.Count) samples)"
if ($interrupted) { exit 1 }
