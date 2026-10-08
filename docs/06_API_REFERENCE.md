# API Reference

Backend Routerの実装から確認できるAPIです。全Endpointは`/api`配下です。

## Health

| Method | Endpoint | Response |
|---|---|---|
| GET | `/api/health` | `{"status":"ok","app":"Argus","version":"0.1.0"}` |

## Monitors

| Method | Endpoint | Request | Response |
|---|---|---|---|
| GET | `/api/monitors` | なし | `{"monitors": MonitorResponse[]}` |
| POST | `/api/monitors` | `MonitorCreate` | `MonitorResponse`、201 |
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
| GET | `/api/records/{id}` | 1件（`value`/`raw_value`/`previous_value`/`usage`/`confidence`/`validation_status`/`display_status`/`baseline_conflict`/`engine`/`model_id`/画像パスと`image_status`） |
| GET | `/api/records/{id}/image/{original\|overlay}` | 記録時に保存した元画像/推論オーバーレイ（JPEG）。保存済みのファイルだけを返し、現在の映像は取得しない。画像が無い/ファイルが無い場合は404（`detail.code`: `IMAGE_NOT_SAVED` / `IMAGE_FILE_MISSING` / `IMAGE_PATH_INVALID`） |
| GET | `/api/records/status` | 記録の有効/無効、Workerの状態 |
| PUT | `/api/records/settings` | `{enabled}`（既定は有効） |

詳細は`docs/READING_RECORDS.md`を参照してください。値は最終運用値（先頭0除去後）で、`raw_value`は元の桁列です。

## データ保存設定（画像保存先・保存ON/OFF・空き容量）

| Method | Endpoint | Request / Response |
|---|---|---|
| GET | `/api/system/data-storage` | `image_root_folder`（未設定はnull）、`effective_image_root`（未設定時は`<data_dir>/images`）、`excel_output_folder`、`save_original_image`、`save_overlay_image`、`storage_warn_free_gb`（既定10）、`storage_stop_free_gb`（既定5） |
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

