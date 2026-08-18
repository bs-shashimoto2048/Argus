# Argus プロジェクト概要

## 概要

Argusは、カメラ映像から計器を遠隔監視するWebアプリケーションです。READMEでは、第2フェーズでMonitor管理、映像ソース設定、接続確認、ライブ映像表示、推論設定の保存基盤を実装していると説明されています。

## 主な機能

- Monitor CRUD
- 動的な監視ダッシュボード
- ローカルカメラ／URL映像ソース設定
- URL接続確認と成功履歴
- Basic認証入力と保存済みパスワードの非表示レスポンス
- OpenCVによる映像取得、再接続、最新フレーム保持
- JPEGスナップショットとMJPEGストリーム
- 推論設定、ROI、前処理設定の保存枠
- InferenceEngine / ModelRegistry interface

YOLO、EasyOCR、Tesseractの実推論、ROI編集、前処理編集はREADME上で未実装です。

## 使用技術

- Backend: Python、FastAPI、Uvicorn、Pydantic、SQLAlchemy、SQLite、OpenCV
- Frontend: React、React Router、Vite、TypeScript
- テスト: pytest、FastAPI TestClient、httpx

詳細は[03_TECH_STACK.md](03_TECH_STACK.md)を参照してください。

## 実行方法

Backend依存関係:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

Frontend依存関係:

```powershell
cd frontend
npm install
```

開発起動:

```powershell
.\scripts\start_backend_dev.ps1
cd frontend
npm run dev
```

Backendの既定ポートは8000です。`start_backend_dev.ps1`は使用中の場合、次の空きポートを選びます。Viteは5173から空きポートを選び、`strictPort`は設定されていません。

## ビルド

Frontendのビルドコマンドは次のとおりです。

```powershell
cd frontend
npm run build
```

Backend用のビルドコマンドは確認できません。

## テスト

`backend/tests/`にpytestテストが存在します。専用のtest scriptは`package.json`およびPowerShellスクリプトには定義されていません。テストの詳細は[09_TESTING.md](09_TESTING.md)を参照してください。

