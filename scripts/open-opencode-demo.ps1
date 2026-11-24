$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
try {
    if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) {
        throw 'OpenCode is not available in PATH. Restart this launcher after installing OpenCode.'
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'open-dashboard.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Guardian dashboard did not open.' }
    Write-Host 'Dashboard opened using a one-time connection ticket. No token was copied to the clipboard.' -ForegroundColor Green
    Write-Host 'Select LIVE in the dashboard. In OpenCode, ask it to read notes.txt.'
    Write-Host 'Check the current OpenCode mode in the dashboard; an existing protection setting remains effective.'
    & (Join-Path $PSScriptRoot 'start-agent.ps1') -Client opencode
    if ($LASTEXITCODE -ne 0) { throw "OpenCode exited with code $LASTEXITCODE." }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
