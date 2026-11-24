param([string]$ModelDirectory = $env:OLLAMA_MODELS)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
try {
    $tags = Invoke-RestMethod 'http://127.0.0.1:11435/api/tags' -TimeoutSec 2
    if ($tags.models.name -contains 'qwen3:8b') { Write-Output 'Ollama demo already available on 127.0.0.1:11435'; exit 0 }
    throw 'Port 11435 is occupied by an unexpected model service.'
} catch {
    if ($_.Exception.Message -like 'Port 11435*') { throw }
}
if (-not $ModelDirectory) { $ModelDirectory=Join-Path $env:USERPROFILE '.ollama\models' }
$modelPath = $ModelDirectory
if (-not (Test-Path -LiteralPath (Join-Path $modelPath 'manifests'))) { throw "Existing model directory not found: $modelPath" }
New-Item -ItemType Directory -Path (Join-Path $projectRoot '.local') -Force | Out-Null
$previousModels=$env:OLLAMA_MODELS
$previousHost=$env:OLLAMA_HOST
try {
    $env:OLLAMA_MODELS=$modelPath
    $env:OLLAMA_HOST='127.0.0.1:11435'
    $exe=(Get-Command ollama.exe).Source
    $process=Start-Process $exe -ArgumentList 'serve' -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot '.local/ollama-demo.log') -RedirectStandardError (Join-Path $projectRoot '.local/ollama-demo.error.log')
    $process.Id | Set-Content -LiteralPath (Join-Path $projectRoot '.local/ollama-demo.pid')
} finally { $env:OLLAMA_MODELS=$previousModels; $env:OLLAMA_HOST=$previousHost }
for($i=0;$i -lt 20;$i++) {
    Start-Sleep -Milliseconds 250
    try { $null=Invoke-RestMethod 'http://127.0.0.1:11435/api/tags' -TimeoutSec 1; Write-Output 'Ollama demo ready on 127.0.0.1:11435'; exit 0 } catch {}
}
throw 'Ollama demo failed to start. Check .local/ollama-demo.error.log.'
