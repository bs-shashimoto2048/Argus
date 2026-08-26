param([int]$StartPort = 8000)

$port = $StartPort
while (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
  $port++
}

# Issue #26: 実際にbindしたポートを共有ファイルへ書き出す。start_frontend_dev.ps1が
# これを読み取ってVite proxy先を自動設定するため、$StartPort(既定8000)が使用中で
# 繰り上がった場合でも、利用者が手動でARGUS_BACKEND_URLを設定する必要がなくなる。
$portFile = Join-Path $PSScriptRoot ".dev-backend-port"
Set-Content -Path $portFile -Value $port -Encoding ascii -NoNewline

Write-Host "Argus Backend: http://localhost:$port"
Write-Host "Frontend proxy target: start_frontend_dev.ps1が自動検出します(手動設定不要)"
try {
  & uvicorn app.main:app --reload --app-dir backend --port $port
} finally {
  Remove-Item -Path $portFile -ErrorAction SilentlyContinue
}
