# Runs backend and frontend test suites and reports both results.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot

Write-Host '--- backend (pytest) ---'
Set-Location (Join-Path $root 'backend')
& '.\.venv\Scripts\python.exe' -m pytest
$backend = $LASTEXITCODE

Write-Host '--- frontend (vitest) ---'
Set-Location (Join-Path $root 'frontend')
npm run test
$frontend = $LASTEXITCODE

Write-Host ''
Write-Host "backend exit $backend | frontend exit $frontend"
if ($backend -ne 0 -or $frontend -ne 0) { exit 1 }
