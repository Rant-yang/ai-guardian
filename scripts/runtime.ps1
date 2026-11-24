function Get-GuardianPython {
    param([string]$ProjectRoot,[switch]$AllowRepair)
    $managed = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    foreach($relative in @('.venv','.venv\Scripts','.venv\Scripts\python.exe')) {
        $path=Join-Path $ProjectRoot $relative
        if((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Refusing a linked project Python environment. Use a regular project-local .venv.'
        }
    }
    if (Test-Path -LiteralPath $managed -PathType Leaf) {
        try {
            & $managed -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info < (3,14) else 1)'
            if($LASTEXITCODE -eq 0) { return $managed }
        } catch { }
        if(-not $AllowRepair) { throw 'Project Python runtime is unavailable or outside supported 3.11-3.13 range. Run setup.ps1 to repair it.' }
    }
    foreach($command in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
        $candidate=$command.Source
        if(-not $candidate -or $candidate -eq $managed) { continue }
        try {
            & $candidate -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info < (3,14) else 1)'
            if($LASTEXITCODE -eq 0) { return $candidate }
        } catch { }
    }
    # Listing installed runtimes does not request a missing version or trigger installation.
    foreach($launcher in @(Get-Command py.exe -All -ErrorAction SilentlyContinue)) {
        if(-not $launcher.Source) { continue }
        try {
            $installed=@(& $launcher.Source -0p 2>$null)
            if($LASTEXITCODE -ne 0) { continue }
            foreach($line in $installed) {
                if([string]$line -notmatch '^\s*-(?:V:)?3\.(?:11|12|13)(?:-64)?\s+\*?\s*(?<runtime>[A-Za-z]:\\.+\.exe)\s*$') { continue }
                $candidate=$Matches['runtime'].Trim()
                if($candidate -eq $managed -or -not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
                & $candidate -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info < (3,14) else 1)'
                if($LASTEXITCODE -eq 0) { return $candidate }
            }
        } catch { }
    }
    throw 'A working Python 3.11-3.13 was not found on PATH or in Python Launcher registrations. Install a supported Python, then rerun setup.ps1. Existing files were preserved.'
}
