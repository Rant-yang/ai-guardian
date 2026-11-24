param([Parameter(Mandatory=$true)][ValidateSet('claude','opencode','gemini','codex')][string]$Client)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'start-background.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Guardian service did not start.' }
Push-Location $projectRoot
try { python scripts/prepare_agents.py; if ($LASTEXITCODE -ne 0) { throw 'Configuration preparation failed.' } } finally { Pop-Location }
Push-Location (Join-Path $projectRoot "demos/$Client")
try {
    if ($Client -eq 'claude') { claude --settings (Join-Path $projectRoot 'demos/claude/guardian.settings.json') }
    elseif ($Client -eq 'opencode') {
        $previousMode = $env:GUARDIAN_MODE
        try { $env:GUARDIAN_MODE='observe'; opencode } finally { $env:GUARDIAN_MODE=$previousMode }
    }
    elseif ($Client -eq 'gemini') { gemini }
    else {
        $pythonExe = (Get-Command python.exe).Source
        $mcpScript = Join-Path $projectRoot 'guardian/mcp_demo.py'
        $tokenPath = Join-Path $projectRoot '.local/access-token'
        $commandSetting = 'mcp_servers.guardian_demo.command=' + (ConvertTo-Json $pythonExe -Compress)
        $argsSetting = 'mcp_servers.guardian_demo.args=' + (ConvertTo-Json @($mcpScript,'--token-file',$tokenPath) -Compress)
        codex -c 'service_tier="fast"' -c $commandSetting -c $argsSetting
    }
} finally { Pop-Location }
