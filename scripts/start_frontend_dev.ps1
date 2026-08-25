param([string]$BackendUrl)

if ($BackendUrl) {
  Write-Host "Argus Frontend proxy target: $BackendUrl (明示指定)"
} else {
  # Issue #26: start_backend_dev.ps1が書き出したポートを自動検出する。
  # Backendの既定ポート(8000)が使用中で繰り上がった場合でも、利用者が毎回
  # ARGUS_BACKEND_URLを手動設定しなくて済むようにするため。
  # ポートファイルが古い(Backendが既に終了している)可能性があるため、
  # 実際にそのポートがLISTENING状態であることも確認してから採用する。
  $portFile = Join-Path $PSScriptRoot ".dev-backend-port"
  $detectedPort = $null
  if (Test-Path $portFile) {
    $candidate = (Get-Content $portFile -Raw).Trim()
    if ($candidate -match '^\d+$' -and (Get-NetTCPConnection -State Listen -LocalPort ([int]$candidate) -ErrorAction SilentlyContinue)) {
      $detectedPort = $candidate
    }
  }
  if ($detectedPort) {
    $BackendUrl = "http://localhost:$detectedPort"
    Write-Host "Argus Frontend proxy target: $BackendUrl (start_backend_dev.ps1のポートを自動検出)"
  } else {
    $BackendUrl = "http://localhost:8000"
    Write-Host "Argus Frontend proxy target: $BackendUrl (既定値。start_backend_dev.ps1を先に起動していないか、自動検出できなかったため既定値を使用)"
  }
}

$env:ARGUS_BACKEND_URL = $BackendUrl
Push-Location (Join-Path $PSScriptRoot "..\frontend")
try {
  & npm run dev
} finally {
  Pop-Location
}
