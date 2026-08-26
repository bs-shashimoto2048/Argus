# Database

## 接続

- ORM: SQLAlchemy 2.x
- DB: SQLite
- 既定ファイル: `data/argus.db`
- DB URL: `ARGUS_DATABASE_URL`、未設定時は`data/argus.db`
- SQLite接続時に`journal_mode=WAL`と`foreign_keys=ON`を設定
- 起動時に`Base.metadata.create_all(engine)`を実行

Migrationツール、migrationファイル、Alembic設定は確認できません。

## Tables / Entity

| Table | Model | 主なカラム |
|---|---|---|
| `monitors` | `Monitor` | `id`, `name`, `display_name`, `location`, `enabled`, `status`（映像Runtime接続状態専用。`connecting`/`running`/`reconnecting`/`stopped`/`error`。RuntimeManager/MonitorRuntimeのみが書き込む）, `created_at`, `updated_at` |
| `video_sources` | `VideoSource` | `id`, `monitor_id`, `source_type`, `device_id`, `url`, `username`, `encrypted_password`, timestamps |
| `url_histories` | `UrlHistory` | `id`, `url`, `username`, `last_verified_at` |
| `inference_settings` | `InferenceSettings` | `method`, `engine`, `model_id`, `device`, FPS、Confidence、IoU、ImageSize、`roi`/`preprocessing`/`reading`（JSON） |
| `latest_results` | `LatestResult` | `value`（Confirmed値）, `previous_value`, `confidence`, `status`（読取・推論状態専用。`disabled`/`pending`/`ok`/`low_confidence`/`read_error`。API上は`inference_status`として返す）, `last_error`, `engine`, `processing_time_ms`, `timestamp` |
| `inference_results` | `InferenceResult` | `value`（Confirmed値の変化時 + heartbeatのみ記録）, `confidence`, `detections`, `processing_time_ms`, `created_at` |

## Relationships

- Monitor : VideoSource = 1 : 0..1
- Monitor : InferenceSettings = 1 : 1（Serviceが未作成時に補完）
- Monitor : LatestResult = 1 : 1（Serviceが未作成時に補完）
- `monitor_id`のForeignKeyは`ondelete="CASCADE"`です。

`LatestResult`/`InferenceResult`は`backend/app/services/result_store.py`が書き込みます（`backend/reading/`のReadingStabilizerが確定したConfirmed Readingを受け取って保存する。Raw推論結果を直接保存することはない）。

`Monitor.status`（映像Runtime接続状態）と`LatestResult.status`（読取・推論状態、API: `inference_status`）は別々の書き込み経路を持つ独立したカラムであり、互いを上書きしない（Issue #29）。`Monitor.status`は`RuntimeManager`経由で`MonitorRuntime`のみが書き込み、`LatestResult.status`は`result_store.save_result()`のみが書き込む。

