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

## 読取安定化（Reading Stabilization）

単発のAI推論結果（Raw Reading）をそのままDashboardの現在値にはせず、直近の読み取り列から
時系列で確認した確定値（Confirmed Reading）だけを運用値として表示します。

```text
InferenceEngine -> Raw Reading -> ReadingStabilizer(多数決/連続一致) -> ReadingValidator(monotonic/rate/桁数)
  -> Confirmed Reading -> ResultStore -> LatestResult -> Dashboard/Detail
```

Monitor詳細画面の推論設定内「読取安定化」セクション（`inference.reading`）で設定します。

| 設定 | 既定値 | 説明 |
|---|---|---|
| `enabled` | `true` | 安定化を有効にする。`false`にすると単発結果をそのままConfirmed扱いにする（互換モード） |
| `mode` | `majority` | `majority`（多数決）または`consecutive`（連続一致） |
| `window_size` | `5` | 直近何件のRaw Readingを保持するか |
| `required_matches` | `3` | Confirmedとみなす一致数（`window_size`以下である必要がある） |
| `min_confidence` | `0.60` | この値未満の平均confidenceで確定した場合は`low_confidence`として値は表示しつつ要確認扱いにする |
| `expected_digits` | `null` | 桁数（小数点除く）が一致しない候補は`invalid_format`として棄却 |
| `decimal_position` | `null` | 右から何桁目に小数点を挿入するか（Leading Zeroは常に保持） |
| `monotonic` | `true` | 積算メーター向け。確定値が前回より減少した候補を`decrease_detected`として棄却 |
| `max_rate_per_minute` | `null` | 1分あたりの変化量の上限。超過候補を`rate_exceeded`として棄却 |
| `max_consecutive_failures` | `5` | この回数連続でエラー/未検出が続くと`read_error`（`no_reading`）へ遷移 |
| `allow_rollover` | `false` | 最大値から0への巻き戻り（例: 999999→000000）を許可するか |
| `rollover_max` | `null` | rollover時の最大値（`allow_rollover=true`かつrate検証を行う場合に必要） |

一時的な異常値（`decrease_detected`/`rate_exceeded`/`invalid_format`/`pending`）はLatestResult/Dashboardの表示を一切変更せず、直前のConfirmed値を保持したまま静かに棄却します。NO_DETECTIONが1回挟まっても値は消えず、`max_consecutive_failures`連続で失敗した場合のみ「読取不能」へ遷移します。

直近のRaw Reading・合意状況はDebug用途のAPIで確認できます（通常UIでは常用しません）。

```
GET /api/monitors/{id}/reading/diagnostics
```

Stabilizer適用前後の比較レポート（Raw件数・Unique値・多数決値・変化回数等）は以下のスクリプトで確認できます。

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
py scripts/reading_stabilizer_report.py --sequence-preset noisy_meter
```

## Model Registry / モデル評価

`data/models/registry.json`が、配置済みモデルのmetadata（`role`: baseline/candidate/production/deprecated、精度要約、推奨conf/iou/imgsz等）を保持します。`GET /api/system/models`で取得でき、推論設定画面の「モデル」欄はこのAPIから選択肢を動的生成します（ファイルが存在しないモデルは「ファイル無し」と表示されます）。

Argus専用の数字検出モデルの学習・評価（Full Reading Exact Match中心の評価、Baseline比較、Benchmark、Failure Analysis）は`docs/METER_DIGIT_MODEL_EVALUATION.md`にまとめています。評価は`backend/scripts/evaluate_meter_model.py`で再現できます（`full`/`benchmark`/`temporal`/`conf-sweep`モード）。実データセット・実ultralytics依存のため通常CIでは実行しません。

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
py -m scripts.evaluate_meter_model full --model <モデルへの絶対パス> --device cpu --label my_model
```

### 開発用データ収集モード

`POST /api/monitors/{id}/reading/capture`で、現在のframeとその推論結果をDataset候補として保存できます。誤操作防止のため既定で無効、環境変数`ARGUS_ENABLE_DATASET_CAPTURE=1`設定時のみ有効になります。保存先は`data/dataset_candidates/`（gitignore対象）で、password等のcredentialは含めません。

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

Frontend（先にBackendを起動しておくこと。Backendが選んだポートを`start_frontend_dev.ps1`が自動検出するため、`ARGUS_BACKEND_URL`を手動設定する必要はない）:

```powershell
.\scripts\start_frontend_dev.ps1
```

Backendを別の起動方法（`start_backend_dev.ps1`を経由しない等）で動かしている場合や、自動検出を上書きしたい場合だけ、`-BackendUrl`で明示指定できる:

```powershell
.\scripts\start_frontend_dev.ps1 -BackendUrl "http://localhost:8001"
```

`frontend`ディレクトリで直接`npm run dev`を実行する場合は、これまでどおり`$env:ARGUS_BACKEND_URL`を自分でBackendの実際のポートに合わせて設定すること（未設定時は`http://localhost:8000`にフォールバックする）。

ViteのFrontendポートは`5180`に固定しています(`strictPort: true`)。LANアクセスするクライアントが知っているURLは1つだけなので、ポートが自動で他の値へ流れて利用者に気づかれないまま古いURLが無効になる事態を防ぐため(Issue #26)。5180が既に使用中の場合はVite側がエラーで起動失敗するので、先に該当プロセスを終了させること。

- Backend: 起動時に表示されたURL
- APIドキュメント: Backend URL + `/docs`
- Frontend: Vite起動時に表示されたURL
- SQLite: `data/argus.db`

## LAN内アクセス（同一社内LAN上の別PCから閲覧・設定する場合）

大規模な本番公開は想定せず、「担当者がたまに別の社内PCから状況確認・設定変更を行う」用途の最小構成です（Issue #26）。

- Frontend（Vite dev server）は`frontend/vite.config.ts`の`server.host: true`により、既定で全ネットワークインターフェース（`0.0.0.0`）へbindします。
- Backendは`--host`を指定しない限りUvicorn既定の`127.0.0.1`のみへbindし、LANから直接到達できません。
- Frontendの`/api/**`はVite proxy（`vite.config.ts`の`server.proxy`）経由で同一PC上のBackend（`localhost`）へ転送されます。Frontend側のコードは相対パスのみを使用しており、`localhost`/`127.0.0.1`のハードコードはありません。そのため、**LAN側のクライアントはFrontendの1つのURLだけ**でDashboard/Monitor Detail/設定画面/プレビュー・Overlay配信まで利用できます。Backendのポートへ直接アクセスする必要はなく、そのポートをLANへ公開する必要もありません。

手順:

1. Argusを起動しているPCのLAN IPを確認する（`ipconfig`のIPv4アドレス）。
2. 別PCのブラウザで `http://<ArgusPCのLAN IP>:<Frontendポート>` を開く。
3. Windows Firewallの受信規則で、**Frontendのポート（TCP）だけ**をPrivate/Domainネットワークに限定して許可する。**Publicネットワークでは許可しないこと。** なお、Private/Domainプロファイル自体が無効化されている環境では、そもそも受信規則が無くても到達できてしまうため、社内ネットワークの実際のFirewallプロファイル状態を事前に確認すること（`Get-NetConnectionProfile` / `Get-NetFirewallProfile`）。

**セキュリティ上の注意（未実装の認証について）**: Argusには現時点でユーザー認証・権限制御が実装されていません。LANアクセスを許可すると、同一LAN上でFrontendのURLへ到達できる誰もが、閲覧だけでなくMonitorの追加・削除、ROI/推論/CSV出力設定の変更まで行える状態になります。多人数が常時アクセスする運用や、信頼できない端末が同居するネットワークでの利用は推奨しません。閲覧専用モードや簡易認証の追加は別Issueとして検討してください。

Internet公開・VPN越し公開・Reverse proxy/HTTPSの本格導入・AD/SSO等の認証基盤・本番サーバー化（Windows Service化等）は本構成の対象外です。

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
- Raw Reading→Confirmed Readingの時系列安定化（多数決/連続一致）、monotonic/rate/桁数のValidation、Reading Diagnostics API
- Argus専用数字検出モデルの学習・Full Reading Exact Match中心の評価（`docs/METER_DIGIT_MODEL_EVALUATION.md`）、Model Registry（`role`付き、`GET /api/system/models`）、Frontend Model選択肢の動的連動、開発用データ収集モード

## 未実装・既知の制限

- Argus専用数字検出モデルは"Production Candidate"（`meter_digits_v2_candidate.pt`、`role=candidate`）に留まっている。追加データ収集（実カメラ3個体・167枚）で`meter_digits_v3_candidate.pt`を再学習したが、Full Reading Exact Matchの改善なし・Temporal StabilizerのFalse Confirmed Reading悪化のため`role=production`への昇格は見送り、`role=rejected_candidate`として記録のみ（詳細: `docs/METER_DIGIT_MODEL_EVALUATION.md` 13章）
- 機械式カウンター方式のメーター（Domain B）は今回のCandidate学習対象外。対応するには専用データ収集・学習が別途必要
- 実際の物理メーター（積算ガスメーター等）を使ったConfirmed値の長時間安定性検証は未実施（この開発環境に物理メーターを継続設置できないため。既存の実メーター写真によるオフライン評価、実カメラ・実YOLOでのNO_DETECTION連続時の`no_reading`遷移は実機で確認済み）
- Alert、グラフ・履歴分析（ConfirmedReadingのみを見る構造は用意済みだが、Alert本体・グラフ画面は未実装）
- `datetime.utcnow()`のdeprecation警告が残っている（DB層のdatetime列が全体的にnaive datetime前提のため、部分的なtimezone-aware化はnaive/aware比較エラーを誘発するリスクがあり、今回のscopeでは見送り）
- カメラ一覧はOpenCVで0〜4番を探索
- URL認証はOpenCVが受け付ける一時的なURL形式に変換して接続します。機器やOpenCVビルドによっては別途プロキシ等が必要です。
- 暗号鍵未設定時は開発用固定キーのため、本番環境では必ず`ARGUS_SECRET_KEY`を設定してください。
- Engine/Device切り替えは対象Monitorのruntime（映像取得含む）を再構成する方式のため、切り替え中は該当Monitorの映像に一瞬の断が生じる（他Monitorには影響しない）。
- ユーザー認証・権限制御は未実装。LANアクセスを許可すると、到達可能な誰もが閲覧だけでなく設定変更まで行えるため注意が必要（詳細は「LAN内アクセス」参照、Issue #26）。
