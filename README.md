# Argus

カメラ映像から計器を遠隔監視するWebアプリケーションです。Monitor管理、映像ソース設定、接続確認、ライブ映像表示、ROI/前処理編集に加え、YOLO（Ultralytics）/ EasyOCR / Tesseractによる実推論、推論結果の保存とDashboard/Detail表示までを実装しています。

## 必要環境

- Python 3.10以上（3.12で動作確認済み）
- Node.js 18以上
- Windowsではカメラ利用時にカメラ権限を許可してください
- 実推論（YOLO/EasyOCR/Tesseract）を使う場合は下記「推論エンジンの導入」を参照

## Backendセットアップ

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

カメラ映像の監視だけ（AI推論なし）であれば、上記のみで起動できます。

## 推論エンジンの導入（YOLO / EasyOCR / Tesseract）

重いAI依存は`requirements.txt`から分離しています。実推論を使う場合のみ追加でインストールしてください。

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements-inference.txt
```

### CPU / GPU設定

上記でインストールされるtorchはCPU版です。NVIDIA GPU（CUDA）で推論する場合は、GPU用のtorchを入れ直してください。お使いのNVIDIA Driverが対応するCUDAバージョンに応じてindex-urlを選びます（対応表: https://pytorch.org/get-started/locally/ ）。

```powershell
# 例: Driverが CUDA 12.1系ランタイムに対応している場合
py -m pip install torch torchvision --force-reinstall --index-url https://download.pytorch.org/whl/cu121
```

torchとtorchvisionは同じCUDA/CPUチャンネルから揃えてインストールしてください（バージョンの組み合わせが合わないと`torchvision::nms does not exist`のようなエラーになります）。

### CUDA環境の確認

Backend起動後、以下のDiagnostics APIでtorch/CUDA/GPU/各ライブラリの導入状況を確認できます（秘密情報・内部パスは返しません）。

```
GET /api/system/inference
```

```json
{
  "torch": {"available": true, "version": "2.5.1+cu121", "cuda_available": true, "cuda_version": "12.1", "device_count": 1, "devices": [{"index": 0, "name": "NVIDIA GeForce RTX 4070 Laptop GPU"}]},
  "ultralytics": {"available": true, "version": "8.4.121"},
  "easyocr": {"available": true},
  "tesseract": {"python_package": true, "executable": true, "version": "5.5.0"},
  "devices": [{"value": "auto", "label": "Auto"}, {"value": "cpu", "label": "CPU"}, {"value": "cuda:0", "label": "GPU 0 - NVIDIA GeForce RTX 4070 Laptop GPU"}]
}
```

Frontendの推論設定画面のDevice選択肢は、このAPIから取得した実環境のGPUのみを表示します（存在しないGPU indexを選択肢に出しません）。

### Tesseract本体（Windows native executable）

`pytesseract`はPythonパッケージですが、実際の文字認識には別途Tesseract本体（`tesseract.exe`）のインストールが必要です。

1. https://github.com/UB-Mannheim/tesseract/wiki からインストーラを取得しインストール
2. PATHへ通すか、既定のインストール先（`C:\Program Files\Tesseract-OCR\tesseract.exe`）にインストールしていればArgusが自動検出します
3. 未導入の場合、TesseractエンジンはBackendを落とさず`TESSERACT_NOT_INSTALLED`エラーを返します（映像表示は継続します）

## Modelの配置方法

数字検出用のYOLOモデル（`.pt`）は`data/models/`に配置します。

```text
data/models/
  meter_digits_v1.pt
```

推論設定の`model_id`にはこのファイル名（例: `meter_digits_v1.pt`）を指定します。絶対パスではなくファイル名で指定することで、環境が変わってもモデルの配置場所に依存しません。存在しないファイルを指定した場合は`MODEL_NOT_FOUND`が返ります。

## Smoke Test

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
py -m pytest -q                                   # 通常のunit/integrationテスト（AI依存なしでも実行可）
py -m pip install -r requirements-inference.txt
py -m pytest -q -m optional_inference             # 実ultralytics/easyocr/tesseractのCPU smoke test
py -m pytest -q -m hardware                       # 実GPU(CUDA)が使える環境でのみ
```

## optional dependencyの考え方

- `requirements.txt`: 映像監視（カメラ/URL/ROI/前処理/Dashboard）だけで使う場合の最小構成。
- `requirements-inference.txt`: YOLO/EasyOCR/Tesseractの実推論を使う場合に追加する重いAI依存。
- pytestの`optional_inference`/`hardware`マーカーで、通常CIに重いAI依存や実GPU/実カメラ依存を持ち込まないようにしています（`backend/pytest.ini`）。

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
- JPEGスナップショット / MJPEGストリーム / 推論結果Overlay JPEG配信
- ROI編集・前処理編集（実画像への適用込み）
- YOLO（Ultralytics）/ EasyOCR / Tesseractによる実推論、ModelRegistryによるモデルcache/reuse
- 推論結果（現在値・信頼度・前回値・推論status/エラー）の保存とDashboard/Detail表示
- Diagnostics API（`GET /api/system/inference`）によるtorch/CUDA/各推論ライブラリの導入状況確認
- Frontend Device選択肢の実環境（実GPU）連動

## 未実装・既知の制限

- Argus専用に学習された高精度な数字検出モデルは未整備（`data/models/meter_digits_v1.pt`は外部で学習済みの持ち込みモデルであり、精度評価は別途必要）
- Alert、グラフ・履歴分析
- カメラ一覧はOpenCVで0〜4番を探索
- URL認証はOpenCVが受け付ける一時的なURL形式に変換して接続します。機器やOpenCVビルドによっては別途プロキシ等が必要です。
- 暗号鍵未設定時は開発用固定キーのため、本番環境では必ず`ARGUS_SECRET_KEY`を設定してください。
- Engine/Device切り替えは対象Monitorのruntime（映像取得含む）を再構成する方式のため、切り替え中は該当Monitorの映像に一瞬の断が生じる（他Monitorには影響しない）。
