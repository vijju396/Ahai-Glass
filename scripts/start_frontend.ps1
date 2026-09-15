# Starts the Vite dev server on port 5173.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root 'frontend')
npm run dev
