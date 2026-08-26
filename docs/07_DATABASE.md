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
| `latest_results` | `LatestResult` | `value`（Confirmed値）, `previous_value`, `confidence`, `status`（読取・推論状態専用。`disabled`/`pending`/`ok`/`low_confidence`/`read_error`。API上は`inference_status`として返す）, `last_error`（値が変わるまで残り続ける履歴用の粘着値。API: `last_inference_error`）, `current_error`（直近のRaw Readingが成功していれば`null`になる、現在の状態専用の値。API: `current_inference_error`。Issue #32）, `engine`, `processing_time_ms`, `timestamp` |
| `inference_results` | `InferenceResult` | `value`（Confirmed値の変化時 + heartbeatのみ記録）, `confidence`, `detections`, `processing_time_ms`, `created_at` |

## Relationships

- Monitor : VideoSource = 1 : 0..1
- Monitor : InferenceSettings = 1 : 1（Serviceが未作成時に補完）
- Monitor : LatestResult = 1 : 1（Serviceが未作成時に補完）
- `monitor_id`のForeignKeyは`ondelete="CASCADE"`です。

`LatestResult`/`InferenceResult`は`backend/app/services/result_store.py`が書き込みます（`backend/reading/`のReadingStabilizerが確定したConfirmed Readingを受け取って保存する。Raw推論結果を直接保存することはない）。

`Monitor.status`（映像Runtime接続状態）と`LatestResult.status`（読取・推論状態、API: `inference_status`）は別々の書き込み経路を持つ独立したカラムであり、互いを上書きしない（Issue #29）。`Monitor.status`は`RuntimeManager`経由で`MonitorRuntime`のみが書き込み、`LatestResult.status`は`result_store.save_result()`のみが書き込む。

`LatestResult.last_error`は値が変わる（＝新たにConfirmed/別のエラーへ遷移する）まで更新されず残り続ける「粘着性」の設計であり、意図的な既存挙動（Alert等の将来利用を想定）である。そのため、一時的なエラーが解消済みでも過去のエラー文言が残り続け、実際の現在の状態と乖離して見えることがあった（Issue #32）。これを受けて追加した`LatestResult.current_error`は、直近1tickのRaw Reading自体が成功していれば（Confirmed/Pending/Rejectedいずれの判定結果であっても）即座に`null`へクリアされる、「現在まさにエラー中かどうか」専用の値。ReadingStabilizer/Validatorの判定ロジック（連続失敗の閾値等）自体には一切変更を加えておらず、`result_store.save_result()`が既に受け取っている`ConfirmedReading.raw_error`を読むだけの追加。Frontend（Monitor Detail）はこの`current_inference_error`を赤い警告表示に使い、`last_inference_error`は現在エラーではない場合のみ「過去のエラー履歴」として控えめに表示する。

