param([int]$StartPort = 8000)

$port = $StartPort
while (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
  $port++
}

Write-Host "Argus Backend: http://localhost:$port"
Write-Host "Frontend proxy target: set ARGUS_BACKEND_URL=http://localhost:$port"
& uvicorn app.main:app --reload --app-dir backend --port $port
