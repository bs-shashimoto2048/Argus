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
| `monitors` | `Monitor` | `id`, `name`, `display_name`, `location`, `enabled`, `status`（映像Runtime接続状態専用。`connecting`/`running`/`reconnecting`/`stopped`/`error`。RuntimeManager/MonitorRuntimeのみが書き込む）, `display_order`（Dashboard/モニター管理の表示順。小さいほど先頭。欠番可。既存DBへの追加時はid昇順の順位0,1,2…で起動時に1回補完、新規は末尾=最大+1）, `created_at`, `updated_at` |
| `video_sources` | `VideoSource` | `id`, `monitor_id`, `source_type`, `device_id`, `url`, `username`, `encrypted_password`, timestamps |
| `url_histories` | `UrlHistory` | `id`, `url`, `username`, `last_verified_at` |
| `inference_settings` | `InferenceSettings` | `method`, `engine`, `model_id`, `device`, FPS、Confidence、IoU、ImageSize、`roi`/`preprocessing`/`reading`（JSON） |
| `latest_results` | `LatestResult` | `value`（Confirmed値）, `previous_value`, `confidence`, `status`（読取・推論状態専用。`disabled`/`pending`/`ok`/`low_confidence`/`read_error`。API上は`inference_status`として返す）, `last_error`（値が変わるまで残り続ける履歴用の粘着値。API: `last_inference_error`）, `current_error`（直近のRaw Readingが成功していれば`null`になる、現在の状態専用の値。API: `current_inference_error`。Issue #32）, `engine`, `processing_time_ms`, `timestamp` |
| `reading_baselines` | `ReadingBaseline` | monotonic基準値（Issue #40）。`monitor_id`（UNIQUE）, `value`/`numeric_value`（CONFIRMEDのみ）, `confirmed_at`, `source`（`confirmed`/`operator_reset`/`operator_rebase`/`auto_semantic_reset`）, `state`（`active`/`pending_reset`）, `epoch`（reset/rebaseの世代番号。古い世代のConfirmedによる上書きを防ぐ）, `decimal_position`/`expected_digits`（semantic fingerprint）, `conflict_*`（基準値と矛盾する合意候補の継続状態）, `updated_at` |
| `reading_baseline_events` | `ReadingBaselineEvent` | baseline操作の監査履歴。`monitor_id`（FKなし。Monitor削除後も残す）, `monitor_name`（スナップショット）, `occurred_at`, `action`（`reset`/`rebase`/`auto_semantic_reset`）, `old_value`, `old_confirmed_at`, `new_value`, `reason`, `operator`, `client_host`, `context`（JSON） |
| `reading_records` | `ReadingRecord` | 1時間ごとの正式な計測記録（1 Monitor 1時間 1件）。`monitor_id`/`monitor_name`（スナップショット）、`hour_bucket`（JSTの計測枠、`(monitor_id, hour_bucket)`でUNIQUE）、`recorded_at`、`value`/`numeric_value`/`raw_value`/`previous_value`/`usage`、`confidence`、`validation_status`、`display_status`、`baseline_conflict`、`engine`/`model_id`、`original_image_path`/`overlay_image_path`/`image_status`/`image_error`（画像保存はPhase 2）、`raw_confidence`（最新Raw側の信頼度）、`inference_at`（その証跡snapshotの推論時刻）、手動修正の状態（`original_value`/`correction_count`/`corrected_at`/`corrected_by`）。Monitor削除後も残す（FKなし） |
| `reading_record_corrections` | `ReadingRecordCorrection` | 読取値（正式値）の手動修正の監査履歴（追記のみ。修正のたびに1行）。`record_id`、`monitor_id`、`corrected_at`、`operator`、`reason`、`old_value`/`new_value`、`old_numeric_value`/`new_numeric_value`、`old_usage`/`new_usage`、修正時点の元証跡のコピー（`raw_value`/`raw_confidence`/`validation_status`/`value_source`/`baseline_value`/`baseline_conflict`/画像パス）、`client_host`、`context`（JSON: 理由の種類・次の記録のusage変化・baseline再設定の実施有無など） |
| `inference_results` | `InferenceResult` | `value`（Confirmed値の変化時 + heartbeatのみ記録）, `confidence`, `detections`, `processing_time_ms`, `created_at` |

`system_settings`には、画像保存・Excel出力の設定（`image_root_folder`、`excel_output_folder`（Phase 3のExcel保存先。未設定時は`<data_dir>/exports`）、`save_original_image`、`save_overlay_image`、`storage_warn_free_gb`、`storage_stop_free_gb`）も追加しました。`reading_records`には`value_source`（confirmed / carried_forward / none）を追加し、既存の記録は起動時に1回だけ補完します（値あり＋検証statusがconfirmed/low_confidenceならconfirmed、値ありでそれ以外はcarried_forward、値なしはnone）。

`system_settings`に`hourly_record_enabled`（1時間ごとの計測記録の有効/無効、既定は有効）を追加しました（起動時に`ALTER TABLE ADD COLUMN`）。`reading_records`も新規テーブルで、`create_all`が自動作成します。

`reading_baselines`/`reading_baseline_events`は新規テーブルで、起動時の`create_all`が自動作成します（既存テーブルの`ALTER`は不要）。既存Monitorにはbaseline行がなく、`latest_results.value`から自動では作りません（過去の誤確定が復活するのを避けるため）。最初のCONFIRMEDで初回baselineが作られます。`monitor_id`はSQLiteで再利用され得るため、監査履歴はMonitorが存在する間はその作成時刻以降のものだけを返します。

## Relationships

- Monitor : VideoSource = 1 : 0..1
- Monitor : InferenceSettings = 1 : 1（Serviceが未作成時に補完）
- Monitor : LatestResult = 1 : 1（Serviceが未作成時に補完）
- `monitor_id`のForeignKeyは`ondelete="CASCADE"`です。

`LatestResult`/`InferenceResult`は`backend/app/services/result_store.py`が書き込みます（`backend/reading/`のReadingStabilizerが確定したConfirmed Readingを受け取って保存する。Raw推論結果を直接保存することはない）。

`Monitor.status`（映像Runtime接続状態）と`LatestResult.status`（読取・推論状態、API: `inference_status`）は別々の書き込み経路を持つ独立したカラムであり、互いを上書きしない（Issue #29）。`Monitor.status`は`RuntimeManager`経由で`MonitorRuntime`のみが書き込み、`LatestResult.status`は`result_store.save_result()`のみが書き込む。

`LatestResult.last_error`は値が変わる（＝新たにConfirmed/別のエラーへ遷移する）まで更新されず残り続ける「粘着性」の設計であり、意図的な既存挙動（Alert等の将来利用を想定）である。そのため、一時的なエラーが解消済みでも過去のエラー文言が残り続け、実際の現在の状態と乖離して見えることがあった（Issue #32）。これを受けて追加した`LatestResult.current_error`は、直近1tickのRaw Reading自体が成功していれば（Confirmed/Pending/Rejectedいずれの判定結果であっても）即座に`null`へクリアされる、「現在まさにエラー中かどうか」専用の値。ReadingStabilizer/Validatorの判定ロジック（連続失敗の閾値等）自体には一切変更を加えておらず、`result_store.save_result()`が既に受け取っている`ConfirmedReading.raw_error`を読むだけの追加。Frontend（Monitor Detail）はこの`current_inference_error`を赤い警告表示に使い、`last_inference_error`は現在エラーではない場合のみ「過去のエラー履歴」として控えめに表示する。

