# AGENTS.md

## Project Overview

Argusは、カメラ映像から計器を遠隔監視するWebアプリケーションです。BackendはFastAPI、FrontendはReact／Vite／TypeScriptです。Monitor CRUD、映像ソース設定、接続確認、ライブ映像表示、推論設定保存枠が実装されています。

## Directory Guide

- `backend/app/`: FastAPI、Schema、Model、Service、Router
- `backend/runtime/`: OpenCV映像取得とMonitor Runtime
- `backend/tests/`: pytestテスト
- `frontend/src/pages/`: 画面
- `frontend/src/components/`: Reactコンポーネント
- `frontend/src/api/`: API client
- `data/`: SQLite DB
- `scripts/`: 開発用PowerShell起動スクリプト
- `docs/`: プロジェクト資料

## Development Rules

- 既存のBackend／Frontend分離を維持する。
- HTTP Router、Service、Model、Schemaの役割分離を維持する。
- Monitorごとの映像処理は`backend/runtime/`と`RuntimeManager`を経由する。
- Frontend API呼び出しは`frontend/src/api/client.ts`を使用する。
- パスワードをAPI responseやログへ平文出力しない。
- 未実装のYOLO、EasyOCR、Tesseract、ROI編集、前処理編集を実装済みとして扱わない。
- API、DB、Runtimeを変更する場合は既存Router・Service・Model・Schemaの整合性を確認する。

## Build Commands

実在するFrontend script:

```powershell
cd frontend
npm install
npm run dev
npm run build
```

Backend開発起動:

```powershell
.\scripts\start_backend_dev.ps1
```

Frontend開発起動スクリプト:

```powershell
.\scripts\start_frontend_dev.ps1
```

## Test Commands

`backend/tests/`にpytestテストがあります。専用test scriptは確認できません。`package.json`にFrontend test scriptはありません。

## Formatting

Formatter、Lint設定、対応コマンドは確認できません。新しいFormatterやLintを追加する場合は、依存関係と設定を別途明示すること。

## Architecture Notes

- FastAPI lifespanがDB table作成と有効Monitor Runtime起動を行う。
- `RuntimeManager`がMonitor IDごとの`MonitorRuntime`を管理する。
- `VideoReader`がOpenCVからframeを読み、`LatestFrameBuffer`が最新JPEGのみ保持する。
- Dashboardはsnapshotをポーリングし、DetailはMJPEG streamを利用する。
- SQLiteはWAL modeとForeign Keyを有効にする。
- 推論関連は`InferenceSettings`モデルと`backend/app/inference/`のinterfaceが存在するが、実推論は未実装。

## Safe Editing Areas

- UI変更: `frontend/src/components/`、`frontend/src/pages/`、`frontend/src/styles.css`
- API処理変更: 対応する`backend/app/routers/`と`backend/app/services/`
- 映像処理変更: `backend/runtime/`と`backend/app/services/video_service.py`
- ドキュメント変更: `docs/`、`README.md`

変更前に既存のAPI契約、Schema、テストを確認すること。

## Sensitive Files

- `frontend/package-lock.json`: npm依存関係のlock file。依存追加以外で不用意に編集しない。
- `data/argus.db`、`data/argus.db-*`: 実行時SQLiteファイル。手動編集・削除をしない。
- `backend/app/core/security.py`: SecretStoreと暗号化処理。
- `backend/app/core/config.py`: DB URL、データディレクトリ、Secret設定。
- `backend/app/models/`: DB schemaに影響するModel。
- `backend/runtime/`: カメラ接続とスレッド処理。

## Development Workflow

リポジトリ内で確認できる範囲の流れ:

```text
実装
↓
Backend tests（専用scriptは未定義）
↓
npm run build
↓
起動スクリプト／npm run devで確認
↓
Commit
```

LintとFormatのコマンドは存在を確認できません。

## Coding Style

- Python classはPascalCase、function／variableはsnake_case。
- React componentはPascalCase。
- API JSON、Python属性、TypeScript型のフィールドはsnake_caseが中心。
- Pydantic `Field`と`Literal`で入力範囲・候補を定義する。
- RouterではServiceの`ValueError`をHTTPExceptionへ変換する。
- `threading.Lock`、`Event`、`Thread`で映像Runtimeを制御する。
- コメントは既存コードでは短い説明コメントとdocstringが使われている。新規コメントは実装理由が必要な箇所に限定する。

## AI Instructions

- 既存設計を優先する。
- 不要なリファクタリングをしない。
- ソースで確認できないAPIや設定を推測で追加しない。
- 未使用ライブラリを追加しない。
- 既存命名規則を守る。
- 既存ディレクトリ構成を維持する。
- 最小変更を基本とする。
- READMEと`docs/`の記載はソースの実態と一致させる。
- TODO/FIXMEが追加された場合は意図を確認し、既存の未実装事項を実装済みと記載しない。

