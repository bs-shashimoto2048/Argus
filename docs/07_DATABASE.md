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
| `monitors` | `Monitor` | `id`, `name`, `display_name`, `location`, `enabled`, `status`, `created_at`, `updated_at` |
| `video_sources` | `VideoSource` | `id`, `monitor_id`, `source_type`, `device_id`, `url`, `username`, `encrypted_password`, timestamps |
| `url_histories` | `UrlHistory` | `id`, `url`, `username`, `last_verified_at` |
| `inference_settings` | `InferenceSettings` | `method`, `engine`, `model_id`, `device`, FPS、Confidence、IoU、ImageSize、JSON設定 |
| `latest_results` | `LatestResult` | `value`, `previous_value`, `confidence`, `timestamp` |
| `inference_results` | `InferenceResult` | `value`, `confidence`, `detections`, `processing_time_ms`, `created_at` |

## Relationships

- Monitor : VideoSource = 1 : 0..1
- Monitor : InferenceSettings = 1 : 1（Serviceが未作成時に補完）
- Monitor : LatestResult = 1 : 1（Serviceが未作成時に補完）
- `monitor_id`のForeignKeyは`ondelete="CASCADE"`です。

推論履歴の書き込み処理は確認できません。`InferenceResult`モデルは存在しますが、実推論処理はREADMEで未実装です。

