$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'start-background.ps1')
    if($LASTEXITCODE -ne 0) { throw 'Guardian failed to start.' }
    $tokenValue=(Get-Content -LiteralPath (Join-Path $projectRoot '.local/admin-token') -Raw).Trim()
    $ticket=Invoke-RestMethod 'http://127.0.0.1:8765/api/launch-ticket' -Method Post -Headers @{Authorization="Bearer $tokenValue"} -ContentType 'application/json' -Body '{}' -TimeoutSec 3
    Start-Process ('http://127.0.0.1:8765/#connect='+$ticket.ticket)
} catch {
    $_.Exception.Message | Set-Content -LiteralPath (Join-Path $projectRoot '.local/launcher-error.log')
    $popup=New-Object -ComObject WScript.Shell
    $null=$popup.Popup(('Guardian could not start. See '+(Join-Path $projectRoot '.local\launcher-error.log')),0,'Guardian',16)
    exit 1
}
