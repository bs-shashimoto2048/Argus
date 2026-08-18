# コーディングルール（コードから確認できる範囲）

## 命名

- PythonのクラスはPascalCase（例: `MonitorRuntime`、`VideoReader`）。
- Pythonの関数・変数はsnake_case（例: `get_monitor`、`monitor_id`）。
- ReactコンポーネントはPascalCaseのファイル・関数名（例: `MonitorCard`）。
- TypeScriptの型名はPascalCase（例: `Monitor`、`Inference`）。
- APIのJSONフィールドはsnake_case（例: `display_name`、`video_fps`）。

## 型定義

- BackendではSQLAlchemyの`Mapped[...]`、Pydanticの`BaseModel`、`Literal`、`Field`を使用しています。
- Frontendでは`type`によるAPIデータ型と、関数引数の型注釈を使用しています。

## Validation

- Monitor名は英数字、`_`、`-`のパターンです。
- ROI、Confidence、IoU、FPS、ImageSizeはPydantic Fieldで範囲を検証します。
- `inference_fps`が`video_fps`を超える場合はPydantic model validatorで拒否します。

## エラー処理

- RouterはServiceの`ValueError`をHTTPExceptionへ変換します。
- Frontend APIクライアントは非2xxレスポンスを`Error`へ変換します。
- 映像接続エラーはユーザー向けメッセージを返します。
- パスワードはAPI responseへ平文で返さず、ログ出力処理も確認できません。

## 非同期・並行処理

- FastAPI lifespanは`asynccontextmanager`を使用します。
- Monitorごとの映像取得はdaemon `Thread`と`threading.Event`で実行します。
- 最新JPEGの共有には`threading.Lock`を使用します。
- Frontendの定期更新には`setInterval`を使用します。

## ファイル配置

- HTTP APIは`backend/app/routers/`。
- アプリケーション処理は`backend/app/services/`。
- SQLAlchemyモデルとPydantic schemaは別ディレクトリ。
- React画面は`frontend/src/pages/`、共通UIは`frontend/src/components/`。

コメント形式、Formatter、Lint設定は専用設定ファイルが確認できないため、追加の規則は記載しません。

