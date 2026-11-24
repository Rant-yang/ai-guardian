param([switch]$CheckOnly, [switch]$NoOpen)
$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
$setupLock=$null
$setupLockHeld=$false
Push-Location $projectRoot
try {
    . (Join-Path $projectRoot 'scripts\runtime.ps1')
    if(-not $CheckOnly) {
        $hasher=[Security.Cryptography.SHA256]::Create()
        try { $setupKey=([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant())))).Replace('-','') }
        finally { $hasher.Dispose() }
        $setupLock=New-Object Threading.Mutex($false,"Local\Guardian-Setup-$setupKey")
        try { $setupLockHeld=$setupLock.WaitOne(15000) } catch [Threading.AbandonedMutexException] { $setupLockHeld=$true }
        if(-not $setupLockHeld) { throw 'Another setup is still running. Wait for it to finish, then rerun this command. No environment was changed by this attempt.' }
    }
    $pythonExe=Get-GuardianPython -ProjectRoot $projectRoot -AllowRepair:(-not $CheckOnly)
    $webviewReady=$false
    $registryLimited=$false
    foreach($reg in @('HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients','HKCU:\Software\Microsoft\EdgeUpdate\Clients','HKLM:\Software\Microsoft\EdgeUpdate\Clients')) {
        try { if(Test-Path $reg) {
            foreach($child in Get-ChildItem $reg) {
                $item=Get-ItemProperty $child.PSPath
                if($item.name -like '*WebView2*' -and $item.pv -and $item.pv -ne '0.0.0.0') { $webviewReady=$true }
            }
        } } catch { $registryLimited=$true }
    }
    Write-Output "Python: $pythonExe"
    Write-Output "WebView2 runtime detected: $webviewReady"
    if($registryLimited) { Write-Warning 'Some registry locations could not be read; detection may be incomplete.' }
    if($CheckOnly) {
        if(-not $webviewReady) { throw 'Desktop prerequisites are incomplete: WebView2 was not detected. No configuration was changed.' }
        Write-Output 'Read-only prerequisite checks complete. Dependency installation and desktop startup have not been verified. No client configuration changed.'
        exit 0
    }
    if(-not $webviewReady) { throw 'Install Microsoft Edge WebView2 Evergreen Runtime first: https://developer.microsoft.com/microsoft-edge/webview2/ . No agent configuration was changed.' }
    $pythonExe=Get-GuardianPython -ProjectRoot $projectRoot -AllowRepair
    $venv=Join-Path $projectRoot '.venv'
    if(Test-Path -LiteralPath $venv) {
        if((Get-Item -LiteralPath $venv).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing a linked .venv directory.' }
    }
    $managedPython=Join-Path $venv 'Scripts\python.exe'
    $managedReady=$false
    if(Test-Path -LiteralPath $managedPython -PathType Leaf) {
        try { & $managedPython -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info < (3,14) else 1)';$managedReady=$LASTEXITCODE -eq 0 } catch { }
    }
    if(-not $managedReady) {
        Write-Output 'Creating or repairing the project Python environment in place; existing files are preserved.'
        & $pythonExe -m venv $venv
        if($LASTEXITCODE -ne 0) { throw 'Could not create the project-local Python environment.' }
    }
    $dependencyCheck=@'
import sys
try:
    import importlib.metadata as m
    from pathlib import Path
    import re
    import webview
    import guardian.server
    rows=[line.strip() for line in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if not rows:raise ValueError('Empty dependency list')
    for row in rows:
        match=re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)',row)
        if not match or m.version(match[1])!=match[2]:raise ValueError('Desktop dependency version mismatch')
except Exception:
    sys.exit(1)
'@
    $requirementsPath=Join-Path $projectRoot 'requirements-desktop.txt'
    & $managedPython -c $dependencyCheck $requirementsPath
    if($LASTEXITCODE -ne 0) {
        & $managedPython -m pip --version
        if($LASTEXITCODE -ne 0) {
            & $managedPython -m ensurepip --upgrade
            if($LASTEXITCODE -ne 0) { throw 'Could not restore pip from the Python runtime. Existing Agent configuration was not changed.' }
        }
        & $managedPython -m pip install --disable-pip-version-check --timeout 15 --retries 1 -r (Join-Path $projectRoot 'requirements-desktop.txt')
        if($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check network/proxy settings and rerun setup. Existing Agent configuration was not changed.' }
    } else { Write-Output 'Project dependencies are already ready; no network installation needed.' }
    & $managedPython -c $dependencyCheck $requirementsPath
    if($LASTEXITCODE -ne 0) { throw 'Installed runtime verification failed.' }
    Write-Output 'Ready. No Agent configuration has been changed. Select clients and review the plan in Guardian.'
    if(-not $NoOpen) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'scripts\open-dashboard.ps1')
        if($LASTEXITCODE -ne 0) { throw 'Installation completed, but Guardian did not open. Check .local/launcher-error.log.' }
    }
} finally {
    if($setupLockHeld) { $setupLock.ReleaseMutex() }
    if($setupLock) { $setupLock.Dispose() }
    Pop-Location
}
