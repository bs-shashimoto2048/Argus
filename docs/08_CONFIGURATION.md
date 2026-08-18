# Configuration

## Backend環境変数

| Variable | 用途 | Default |
|---|---|---|
| `ARGUS_DATA_DIR` | データディレクトリ | プロジェクトルートの`data` |
| `ARGUS_DATABASE_URL` | SQLAlchemy DB URL | `sqlite:///{ARGUS_DATA_DIR}/argus.db` |
| `ARGUS_SECRET_KEY` | Fernet暗号鍵 | 未設定時は開発用固定キーを生成 |

`ARGUS_SECRET_KEY`未設定時の固定キーは本番用途では使用しないようREADMEで注意されています。

## Frontend環境変数

| Variable | 用途 | Default |
|---|---|---|
| `ARGUS_BACKEND_URL` | Vite `/api` proxyのtarget | `http://localhost:8000` |

## 固定設定

- FastAPI app name: `Argus`
- FastAPI version: `0.1.0`
- Backend CORS: localhost、127.0.0.1、`[::1]`の任意ポートを正規表現で許可
- Backend開発起動の開始ポート: 8000
- Vite開発起動の開始ポート: 5173（Vite標準動作）
- URL映像のOpenCV timeout: open/readとも8000ms
- OpenCV buffer size: 1
- カメラ探索範囲: device index 0〜4

環境変数ファイルの読み込み設定は確認できません。

