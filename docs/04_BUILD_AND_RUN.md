# Build / Run

## Install

Backend:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

Frontend:

```powershell
cd frontend
npm install
```

## Run

Backend:

```powershell
.\scripts\start_backend_dev.ps1
```

このスクリプトは既定8000から空きポートを探索し、`uvicorn app.main:app --reload --app-dir backend --port $port`を実行します。

Frontend:

```powershell
cd frontend
npm run dev
```

Backend URLを指定する場合は、READMEに記載された`ARGUS_BACKEND_URL`を使用します。Viteの`server.proxy["/api"]`のtargetにも同じ環境変数が使われます。Viteは標準の空きポート選択を利用し、`strictPort`設定はありません。

Frontend用PowerShellスクリプト:

```powershell
.\scripts\start_frontend_dev.ps1
```

このスクリプトは`ARGUS_BACKEND_URL`を設定して`npm run dev`を実行します。

## Build

```powershell
cd frontend
npm run build
```

`npm run build`は`tsc -b && vite build`です。

## Test / Lint / Format / Package

- Backendテスト用の専用scriptは確認できません。
- Frontendのtest、lint、format、package用npm scriptは`package.json`にありません。
- Dockerfile、docker-compose、GitHub Actions、CI/CD設定は確認できません。

