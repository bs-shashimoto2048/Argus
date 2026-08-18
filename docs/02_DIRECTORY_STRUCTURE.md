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
│  ├─ runtime/          映像Runtime
│  ├─ tests/            pytestテスト
│  └─ requirements.txt  Python依存関係
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
├─ data/                SQLite DBとSQLite補助ファイル
├─ scripts/             開発用PowerShell起動スクリプト
├─ docs/                プロジェクトドキュメント
├─ README.md            セットアップと制限事項
└─ .gitignore           生成物・環境ファイルの除外
```

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
| `frontend/src/App.tsx` | Route、App Shell、Background |
| `frontend/src/api/client.ts` | Frontend API呼び出し |
| `frontend/src/pages/DashboardPage.tsx` | Dashboard画面 |
| `frontend/src/pages/MonitorDetailPage.tsx` | Detail画面 |
| `frontend/src/styles.css` | 共通UI、Responsive、Background |

