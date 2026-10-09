# API Reference

Backend Routerの実装から確認できるAPIです。全Endpointは`/api`配下です。

## Health

| Method | Endpoint | Response |
|---|---|---|
| GET | `/api/health` | `{"status":"ok","app":"Argus","version":"0.1.0"}` |

## Monitors

| Method | Endpoint | Request | Response |
|---|---|---|---|
| GET | `/api/monitors` | なし | `{"monitors": MonitorResponse[]}`。**表示順（`display_order` ASC → `id` ASC）**で返す。`MonitorResponse.display_order`は表示順（小さいほど先頭、欠番あり） |
| PUT | `/api/monitors/order` | `{"monitor_ids": [4, 2, 3]}`（全MonitorのIDを表示したい順に指定） | `{"monitor_ids": [...]}`。**1 transaction**で`display_order`を0,1,2…へ更新する（途中までの更新は残さない）。重複ID→422 `DUPLICATE_ID`、存在しないID→422 `UNKNOWN_MONITOR`、全Monitorが含まれない（一覧が更新された可能性）→409 `ORDER_STALE`。`updated_at`は更新しない。Dashboard・モニター管理・履歴のMonitor選択・Excelのworksheet順に反映される |
| POST | `/api/monitors` | `MonitorCreate` | `MonitorResponse`、201。新規Monitorは表示順の末尾（現在の最大`display_order` + 1）へ追加 |
| GET | `/api/monitors/{monitor_id}` | なし | `MonitorResponse` |
| PATCH | `/api/monitors/{monitor_id}` | `MonitorUpdate` | `MonitorResponse` |
| DELETE | `/api/monitors/{monitor_id}` | なし | 204 |

### MonitorCreate

```json
{
  "name": "meter_001",
  "display_name": "第1工場 ガスメーター",
  "location": "第1工場"
}
```

### MonitorUpdate

`display_name`、`location`、`enabled`、`source`、`inference`を任意で含めます。
`inference.reading`で時系列安定化設定（`enabled`/`mode`/`window_size`/`required_matches`/`min_confidence`/`expected_digits`/`decimal_position`/`monotonic`/`max_rate_per_minute`/`max_consecutive_failures`/`allow_rollover`/`rollover_max`）を指定できます。

## Sources

| Method | Endpoint | Request | Response |
|---|---|---|---|
| POST | `/api/sources/check` | `VideoSourceInput` | `ConnectionCheckResponse` |
| GET | `/api/url-history` | なし | `{"items": UrlHistoryResponse[]}` |
| DELETE | `/api/url-history/{history_id}` | なし | 204 |

接続確認が成功し、`source_type`が`url`の場合、URL履歴を保存します。

## Cameras

| Method | Endpoint | Response |
|---|---|---|
| GET | `/api/cameras` | `{"cameras":[{"device_id": number, "label": string}]}` |

OpenCVのカメラ番号0〜4を探索します。

## Streams

| Method | Endpoint | Response |
|---|---|---|
| GET | `/api/monitors/{monitor_id}/snapshot` | `image/jpeg` |
| GET | `/api/monitors/{monitor_id}/preview.jpg` | `image/jpeg`（snapshotと同じ） |
| GET | `/api/monitors/{monitor_id}/overlay.jpg` | `image/jpeg`（検出bbox/class/confidence描画済み。overlay未生成時はsnapshotへfallback） |
| GET | `/api/monitors/{monitor_id}/stream` | `multipart/x-mixed-replace; boundary=frame` |
| GET | `/api/monitors/{monitor_id}/stream.mjpg` | `multipart/x-mixed-replace; boundary=frame`（streamと同じ） |
| GET | `/api/monitors/{monitor_id}/runtime` | Runtime診断（state/frame_size/inference_enabled等） |

Runtimeが存在しない場合は409、最新フレームがない場合は503です。

## Reading（時系列安定化）

| Method | Endpoint | Response |
|---|---|---|
| GET | `/api/monitors/{monitor_id}/reading/diagnostics` | Raw Reading直近N件、Confirmed値、agreement_count、consecutive_failures |
| GET | `/api/monitors/{monitor_id}/reading/baseline` | baseline（基準値）、conflict、最新のRaw合意候補、reading設定 |
| POST | `/api/monitors/{monitor_id}/reading/baseline/reset` | baselineをクリア（次のCONFIRMEDを新baselineにする）。Body: `reason`, `operator`（必須） |
| POST | `/api/monitors/{monitor_id}/reading/baseline/rebase` | baselineを指定値へ再設定。Body: `value`, `reason`, `operator`（必須）, `force`（任意） |
| GET | `/api/monitors/{monitor_id}/reading/baseline/events` | baseline操作の監査履歴（新しい順、`limit`=1〜200）。Monitor削除後も取得可能 |
| POST | `/api/monitors/{monitor_id}/reading/capture` | 現在frame+推論結果をDataset候補として保存（開発者向け、既定403） |

`reading/baseline*`はMonitor詳細の「読取基準値」が使います。`reset`/`rebase`の入力不正は422（`value`の形式・`expected_digits`・`decimal_position`、`reason`/`operator`の欠落や空白）、`reading.enabled=false`は409（`detail.code=READING_DISABLED`）、最新のRaw合意値と大きく異なる値を`force`なしで指定した`rebase`は409（`detail.code=FORCE_REQUIRED`、`candidate`/`tolerance`付き）です。操作はbaselineだけを変更し、`latest_results`の表示値は直接書き換えません（次の正常なConfirmedで更新）。`operator`は認証が未導入のため自己申告で、`client_host`も監査へ保存します。`GET /api/monitors/{id}`の`reading_baseline`には、baselineの要約とconflict（合意候補がbaselineと矛盾して5分以上継続しているか）が含まれます。`reading/diagnostics`には`baseline`/`candidate`/`conflict`が追加されます（値は確定値の形式、Rawは元の桁列）。

Debug用途のAPIで、通常UIで常用する想定はありません。password/認証URL等は含みません。Runtime未稼働時は409です。`reading/capture`は`ARGUS_ENABLE_DATASET_CAPTURE=1`未設定時は常に403を返します（誤操作防止）。

## 計測履歴（reading_records、1時間ごと）

| Method | Endpoint | Response |
|---|---|---|
| GET | `/api/records` | 1時間ごとの計測履歴（新しい順）。Query: `monitor_id`（複数可）、`from`/`to`（記録時刻、ISO 8601、タイムゾーンなしはJST）、`limit`（1〜1000）、`offset`。`{items, total, limit, offset}` |
| GET | `/api/records/{id}` | 1件（`raw_confidence`（最新Raw側の信頼度。`confidence`は正式値側）/`inference_at`（証跡snapshotの推論時刻）/`snapshot_consistent`/`is_corrected`/`correction_count`/`original_value`/`corrected_at`/`corrected_by`/`correctable`/`correctable_reason`も含む。`value`/`raw_value`/`previous_value`/`usage`/`confidence`/`validation_status`/`display_status`/`baseline_conflict`/`engine`/`model_id`/画像パスと`image_status`） |
| GET | `/api/records/{id}/image/{original\|overlay}` | 記録時に保存した元画像/推論オーバーレイ（JPEG）。保存済みのファイルだけを返し、現在の映像は取得しない。画像が無い/ファイルが無い場合は404（`detail.code`: `IMAGE_NOT_SAVED` / `IMAGE_FILE_MISSING` / `IMAGE_PATH_INVALID`） |
| GET | `/api/records/status` | 記録の有効/無効、Workerの状態 |
| PUT | `/api/records/settings` | `{enabled}`（既定は有効） |
| POST | `/api/records/{id}/correct` | 読取値（正式値）の手動修正。Body: `{value, reason, operator, rebase_current_baseline?: bool（既定false）}`。修正できるのは `value_source=carried_forward` または基準値競合中（`baseline_conflict` / `validation_status`=`decrease_detected`・`rate_exceeded`）の記録だけ。`value`は桁・小数位置を検証（`expected_digits`/`decimal_position`）。`reason`/`operator`必須。修正で`value`/`numeric_value`と、連動する`usage`/`previous_value`（その記録と次の1時間の記録）だけを更新し、Raw・信頼度・判定・画像・`value_source`・`inference_at`は変更しない。`rebase_current_baseline=true`のときだけ既存のrebase処理も呼ぶ（既定は現在のbaselineを変更しない）。応答: `{record_id, correction, next_record, rebase, record}`。エラー: 404 `RECORD_NOT_FOUND` / 409 `NOT_CORRECTABLE`（通常のconfirmed記録）・`REBASE_FORCE_REQUIRED` / 422 `REASON_REQUIRED`・`OPERATOR_REQUIRED`・`INVALID_VALUE`・`NO_CHANGE` |
| GET | `/api/records/{id}/corrections` | 記録の修正履歴（新しい順）。`{record_id, corrections[{id, corrected_at, operator, reason, old_value, new_value, old_usage, new_usage, raw_value, raw_confidence, validation_status, value_source, baseline_value, baseline_conflict, original_image_path, overlay_image_path, client_host, context}]}`。監査の正本は`reading_record_corrections`テーブル（UPDATEせず追記のみ） |
| POST | `/api/records/export/excel` | `reading_records`からExcel(.xlsx)を出力（Phase 3）。Body: `{monitor_ids?: number[]（空=全Monitor）, period?: "today"\|"last_7_days"\|"custom"（既定custom）, from?, to?（ISO 8601、タイムゾーンなしはJST。toは含まない）, save_to_server?: bool（既定false）}`。`save_to_server=false`: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`のダウンロード（`Content-Disposition`にファイル名）。`true`: 設定のExcel保存先へ保存し、`{saved, path, filename, folder, size_bytes, total_rows, sheets[{monitor_id, sheet_name, rows}], image_links, image_links_skipped}`を返す。エラー: 422（期間不正・from≧to）、404 `NO_RECORDS`（該当記録なし）、409 `EXPORT_IN_PROGRESS`（別の出力を実行中）、503 `EXPORT_SAVE_FAILED` / `EXPORT_SAVE_TIMEOUT`（保存先の不通・権限・タイムアウト。映像・推論・Reading・定時記録・画像保存には影響しない） |

詳細は`docs/READING_RECORDS.md`を参照してください。値は最終運用値（先頭0除去後）で、`raw_value`は元の桁列です。

## データ保存設定（画像保存先・保存ON/OFF・空き容量）

| Method | Endpoint | Request / Response |
|---|---|---|
| GET | `/api/system/data-storage` | `image_root_folder`（未設定はnull）、`effective_image_root`（未設定時は`<data_dir>/images`）、`excel_output_folder`（未設定はnull）、`effective_excel_output_folder`（未設定時は`<data_dir>/exports`）、`save_original_image`、`save_overlay_image`、`storage_warn_free_gb`（既定10）、`storage_stop_free_gb`（既定5） |
| PUT | `/api/system/data-storage` | 指定した項目だけ更新。保存先は絶対パス（ドライブ付き/UNC）。空文字は未設定。停止しきい値は警告しきい値以下。不正は422 |
| POST | `/api/system/data-storage/test` | `{target: image\|excel, path?}`。書き込みテスト（一時ファイルの作成と削除）と空き容量。常に200で`{ok, message, free_gb}`（UNCの不通でも固まらず、10秒でタイムアウト） |
| GET | `/api/system/data-storage/status` | 画像保存の状態（`state`: ok/warning/stopped/failing/disabled）、空き容量、キュー長、成功/失敗/破棄の件数、最終エラー |

詳細は`docs/READING_RECORDS.md`を参照してください。

## ROI / Preprocess

| Method | Endpoint | Request | Response |
|---|---|---|---|
| GET | `/api/monitors/{monitor_id}/roi` | なし | `Roi` |
| PUT | `/api/monitors/{monitor_id}/roi` | `Roi` | `Roi`（稼働中Runtimeへ即時反映） |
| POST | `/api/monitors/{monitor_id}/preprocess/preview` | `PreprocessSettings` | `image/jpeg` |

## System

| Method | Endpoint | Response |
|---|---|---|
| GET | `/api/system/inference` | torch/CUDA/ultralytics/easyocr/tesseractの導入状況、実環境のdevice一覧 |
| GET | `/api/system/models` | `data/models/registry.json`のModel Catalog（`role`/精度要約/推奨conf・iou・imgsz等） |

