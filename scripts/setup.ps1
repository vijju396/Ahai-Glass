# One-time local setup: backend venv + dependencies, frontend packages.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

Write-Host 'Creating the backend virtual environment...'
Set-Location (Join-Path $root 'backend')
if (-not (Test-Path '.\.venv')) { python -m venv .venv }
& '.\.venv\Scripts\python.exe' -m pip install --upgrade pip
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt

Write-Host 'Installing frontend packages...'
Set-Location (Join-Path $root 'frontend')
npm install

Write-Host 'Setup complete. Run scripts\start_backend.ps1 and scripts\start_frontend.ps1.'
