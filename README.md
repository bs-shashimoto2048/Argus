# Argus

カメラ映像から計器を遠隔監視するWebアプリケーションです。第2フェーズでは、Monitor管理、映像ソース設定、接続確認、ライブ映像表示、推論設定の保存基盤を実装しています。

## 必要環境

- Python 3.10以上
- Node.js 18以上
- Windowsではカメラ利用時にカメラ権限を許可してください

## Backendセットアップ

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

## Frontendセットアップ

```powershell
cd frontend
npm install
```

## 起動方法

Backend（既存API契約の既定ポートは8000。使用中なら開発用スクリプトが次の空きポートを選択）:

```powershell
.\scripts\start_backend_dev.ps1
```

Frontend:

```powershell
cd frontend
# Backendが8000以外の場合だけ指定。未指定時はhttp://localhost:8000
$env:ARGUS_BACKEND_URL = "http://localhost:8001"
npm run dev
```

ViteのFrontendポートは固定していません。5173が使用中なら5174、以降の空きポートをViteが自動選択します。`strictPort`は使用していません。

- Backend: 起動時に表示されたURL
- APIドキュメント: Backend URL + `/docs`
- Frontend: Vite起動時に表示されたURL
- SQLite: `data/argus.db`

## 映像ソース

ローカルカメラはWindowsではOpenCVの`CAP_DSHOW`を使用して探索します。ネットワーク映像はURL方式を選び、`rtsp://`、`http://`、MJPEG等のOpenCV対応URLを入力してください。接続確認では実際に1フレームを取得します。

詳細画面はMJPEG、ダッシュボードは最新JPEGのポーリングで映像を表示します。古いフレームを蓄積せず、各MonitorRuntimeは最新フレームだけを保持します。

## Basic認証

パスワードはAPIレスポンスやログに返しません。DBにはSecretStoreを通して暗号化して保存します。現在のPoCは`ARGUS_SECRET_KEY`を使用する暗号化実装です。同じキーと実行環境が必要で、Windows DPAPIへ置き換える場合は実行ユーザーが変わると復号できない可能性があります。URLへ認証情報を恒久的に埋め込んで保存しません。

## 実装済み

- FastAPI / React / Vite起動
- SQLite（WAL）
- Monitor CRUD
- 動的ダッシュボード
- Monitor追加・詳細画面
- ローカルカメラ、URLソース設定
- URL接続確認・成功履歴・履歴削除
- Basic認証入力と非表示レスポンス
- OpenCV映像取得、再接続、最新フレームバッファ
- JPEGスナップショット / MJPEGストリーム
- 推論設定、ROI、前処理設定の保存枠
- 交換可能なInferenceEngine / ModelRegistry interface

## 未実装・既知の制限

- YOLO、EasyOCR、Tesseractの実推論
- ROI編集、前処理編集
- 実推論結果・履歴・アラート
- GPU実推論
- カメラ一覧はOpenCVで0〜4番を探索
- URL認証はOpenCVが受け付ける一時的なURL形式に変換して接続します。機器やOpenCVビルドによっては別途プロキシ等が必要です。
- 暗号鍵未設定時は開発用固定キーのため、本番環境では必ず`ARGUS_SECRET_KEY`を設定してください。
