# ディレクトリ構成

```text
Argus/
├─ backend/
│  ├─ app/
│  │  ├─ core/          設定、DB、SecretStore
│  │  ├─ inference/     推論interface
│  │  ├─ models/        SQLAlchemyモデル
│  │  ├─ routers/       FastAPI Router
│  │  ├─ schemas/       Pydantic schema
│  │  ├─ services/      アプリケーションサービス
│  │  └─ main.py        FastAPIエントリポイント
│  ├─ runtime/          映像Runtime、InferenceScheduler
│  ├─ reading/          Raw Reading→Confirmed Readingの時系列安定化・Validation
│  ├─ evaluation/       メーター読み取り精度評価のpure function（Full Reading Exact Match等）
│  ├─ scripts/          開発用スクリプト（テスト動画生成、Stabilizer/Model前後比較レポート等）
│  ├─ tests/            pytestテスト（tests/fixtures/にOCR用数字画像生成ヘルパー）
│  ├─ pytest.ini        pytest marker設定（unit/integration/optional_inference/hardware）
│  ├─ requirements.txt  Python依存関係（camera-only運用の最小構成）
│  └─ requirements-inference.txt  YOLO/EasyOCR/Tesseract用の追加依存
├─ frontend/
│  ├─ public/assets/    アイコン画像
│  ├─ src/api/          APIクライアント
│  ├─ src/components/   React共通コンポーネント
│  ├─ src/pages/        React画面
│  ├─ src/App.tsx       RouteとApp Shell
│  ├─ src/main.tsx      React起動
│  ├─ src/styles.css    グローバルCSS
│  ├─ package.json      npm scriptsと依存関係
│  └─ vite.config.ts    Vite設定とAPI proxy
├─ data/
│  ├─ argus.db          SQLite DBとSQLite補助ファイル
│  ├─ models/           YOLOモデル配置先（例: meter_digits_v1.pt）とregistry.json（role等のmetadata）
│  ├─ eval/             モデル評価用Test Set（gitignore対象、manifestのみbackend/tests/fixtures/へcommit）
│  └─ dataset_candidates/  開発用データ収集モードの保存先（gitignore対象、既定無効）
├─ .github/workflows/   CI（ci.yml: 通常CI／inference-smoke.yml: 手動の重い依存Smoke Test）
├─ scripts/             開発用PowerShell起動スクリプト
├─ docs/                プロジェクトドキュメント
├─ README.md            セットアップと制限事項
└─ .gitignore           生成物・環境ファイルの除外
```

## `data/models/` の配置ルール

推論設定の`model_id`は、`data/models/`からの相対ファイル名で指定する（絶対パスは指定しない）。

```text
data/models/
  meter_digits_v1.pt      # model_id: "meter_digits_v1.pt"
```

`YoloInferenceEngine`は`model_id`を`data/models/`基準で解決し、`data/models/`の外を指すパスや存在しないファイルは`MODEL_NOT_FOUND`として扱う。モデルファイルはリポジトリ内に直接コミットする（LFS等は未導入）。

## 主要ファイル

| ファイル | 役割 |
|---|---|
| `backend/app/main.py` | FastAPI生成、Router登録、起動・終了処理 |
| `backend/app/core/config.py` | 環境変数とアプリ設定 |
| `backend/app/core/database.py` | SQLAlchemy Engine、WAL、Session |
| `backend/app/routers/monitors.py` | Monitor CRUD API |
| `backend/app/routers/sources.py` | 接続確認、URL履歴API |
| `backend/app/routers/streams.py` | Snapshot、MJPEG API |
| `backend/runtime/runtime_manager.py` | MonitorRuntimeの管理 |
| `backend/runtime/video_reader.py` | OpenCV入力と接続確認 |
| `backend/runtime/inference_scheduler.py` | ROI/前処理/推論実行、ReadingStabilizer呼び出し、overlay生成 |
| `backend/reading/stabilizer.py` | 多数決/連続一致によるConfirmed Readingの決定 |
| `backend/reading/validator.py` | monotonic/rate/桁数のValidation（pure function） |
| `backend/app/routers/reading.py` | Reading Diagnostics API、開発用データ収集モード |
| `backend/evaluation/metrics.py` | Full Reading Exact Match等のメーター読み取り精度指標（pure function） |
| `backend/scripts/evaluate_meter_model.py` | Baseline/Candidateモデルの評価・Benchmark・Temporal評価スクリプト |
| `backend/app/inference/model_catalog.py` | `data/models/registry.json`を読み込むModel Catalog |
| `backend/app/routers/system.py` | Diagnostics API（`/api/system/inference`）、Model Catalog API（`/api/system/models`） |
| `frontend/src/App.tsx` | Route、App Shell、Background |
| `frontend/src/api/client.ts` | Frontend API呼び出し |
| `frontend/src/pages/DashboardPage.tsx` | Dashboard画面 |
| `frontend/src/pages/MonitorDetailPage.tsx` | Detail画面 |
| `frontend/src/styles.css` | 共通UI、Responsive、Background |

