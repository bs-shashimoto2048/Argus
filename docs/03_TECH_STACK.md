# 技術スタック

## Backend

| 名称 | 用途 | 使用箇所 | Version |
|---|---|---|---|
| Python | Backend実行環境 | `backend/**/*.py` | READMEでは3.10以上 |
| FastAPI | HTTP API | `backend/app/main.py`、`backend/app/routers/` | `>=0.110` |
| Uvicorn | ASGI起動 | `scripts/start_backend_dev.ps1` | `standard>=0.29` |
| Pydantic | Request/Response validation | `backend/app/schemas/` | `>=2.6` |
| SQLAlchemy | ORM、DBアクセス | `backend/app/models/`、`core/database.py` | `>=2.0` |
| SQLite | 設定・結果保存DB | `data/argus.db`、`core/database.py` | Python/SQLite利用 |
| OpenCV | カメラ・URL映像取得、JPEG化 | `backend/runtime/video_reader.py`、`monitor_runtime.py` | `>=4.9` |
| Pillow | requirementsに記載 | 使用箇所は確認できない | `>=10.0` |
| cryptography | SecretStoreのFernet暗号化 | `backend/app/core/security.py` | `>=42.0` |
| pytest | Backendテスト | `backend/tests/` | `>=8.0` |
| httpx | テスト依存 | requirementsに記載 | `>=0.27` |

## Frontend

| 名称 | 用途 | 使用箇所 | Version |
|---|---|---|---|
| Node.js | Frontend実行環境 | README | 18以上 |
| React | UI | `frontend/src/` | `^18.3.1` |
| React DOM | React起動 | `frontend/src/main.tsx` | `^18.3.1` |
| React Router DOM | 画面ルーティング | `frontend/src/App.tsx` | `^6.26.0` |
| Vite | 開発サーバー、ビルド | `frontend/vite.config.ts`、`package.json` | `^5.4.0` |
| TypeScript | Frontend型付け | `frontend/src/`、`tsconfig.json` | package-lockで確認できる依存 |
| @vitejs/plugin-react | Vite React plugin | `frontend/vite.config.ts` | `^4.3.1` |
| @types/react | React型定義 | package.json | `^18.3.3` |
| @types/react-dom | React DOM型定義 | package.json | `^18.3.0` |

YOLO、EasyOCR、Tesseractの実装ライブラリはrequirements/package.jsonに存在しません。

