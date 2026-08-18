param([string]$BackendUrl = "http://localhost:8000")

$env:ARGUS_BACKEND_URL = $BackendUrl
Write-Host "Argus Frontend proxy target: $BackendUrl"
Push-Location (Join-Path $PSScriptRoot "..\frontend")
try {
  & npm run dev
} finally {
  Pop-Location
}
