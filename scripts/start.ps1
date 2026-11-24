param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try { python -m guardian.server --port $Port } finally { Pop-Location }
