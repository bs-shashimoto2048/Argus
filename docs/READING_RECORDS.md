# 1時間ごとの計測履歴（reading_records）

正式な計測記録は「**1 Monitor 1時間 1件**」です。値が変わるたびの記録ではありません（変化の履歴は
`inference_results`）。Excel出力・履歴画面・記録画像は、この記録を基にします（UI再設計 Phase 1: 記録とAPI / Phase 2: 記録画像 / Phase 3: Excel出力）。

## 記録のタイミング

- 毎時00分（Asia/Tokyo）の計測枠（`hour_bucket`、例 `2026-10-08T14:00:00+09:00`）ごとに記録する。既定は有効
  （`PUT /api/records/settings` で無効化できる）。
- 内部は30秒ごとに計測枠を確認し、`(monitor_id, hour_bucket)` のUNIQUE制約により、何度確認しても1件。
- 計測枠の開始から**10分**を過ぎた枠は記録しない（遅れた値を定時計測にしない）。Backend再起動直後でも、10分以内なら
  `recorded_at`（実際の記録時刻）が遅れた形で記録される。
- 映像/読取が正常（正常・要確認）なら即時に記録。正常でない間は、立ち上がり（再起動直後など）を待つため**2分**待ち、
  それでも正常でなければ、その時点の状態（`display_status`、値の有無は下記`value_source`）で記録を作る。
- 対象は、有効（enabled）で映像ソースのあるMonitorだけ。

## 記録する値

| 列 | 内容 |
|---|---|
| `value` | 正式記録値（先頭0除去後）。映像が稼働中なら**直前の正常Confirmed値**（「直近の最高値」ではない）。映像が稼働していない（通信異常・停止中・接続中）間、または確定値が一度も無い場合は `null` |
| `value_source` | `confirmed`: 記録時点の最新候補が正常に確定した値 / `carried_forward`: 最新Rawは棄却中（pending・invalid_format・decrease_detected・rate_exceeded・no_reading等。桁の回転途中・見切れ中を含む）だが、直前の正常Confirmed値を保持した / `none`: 正式に記録できるConfirmed値が無い |
| `raw_value` | 記録時点の最新Raw（先頭0を含む元の桁列）。runtime稼働中のみ。`carried_forward`のときは`value`と一致しないことがある |
| `previous_value` | 前回（1時間前の枠）の定時計測値。前回の記録が無い、または値なしなら `null` |
| `usage` | 今回 − 前回の定時計測値（Decimalの文字列）。下記の場合は `null` |
| `confidence` / `validation_status` / `display_status` | 信頼度、検証status、記録時点の表示状態（正常/要確認/読取不能/通信異常 等） |
| `baseline_conflict` | 記録時点でbaseline conflictの警告中か |
| `engine` / `model_id` / `monitor_name` | 記録時点のengine、model、Monitor表示名のスナップショット |
| 画像列 | `original_image_path` / `overlay_image_path`（画像保存先からの相対パス）/ `image_status` / `image_error`（下記「記録画像」） |

### 使用量（usage）が `null` になる場合
前回の記録なし／前回または今回の値なし／値が減少／どちらかの`display_status`が正常・要確認以外／どちらかが
baseline conflict／前回の記録以降にbaselineのreset・rebase・自動クリアがあった（正常な連続データではない）。
値が変わらない場合は `0`（欠損ではない）。

## 状態変化との関係
通信異常・読取不能・baseline conflict・reset/rebase等の**状態イベントは、この計測履歴に独立した行として混在させない**。
既存の `reading_baseline_events`（baseline操作の監査履歴）とruntime情報で扱い、将来、専用のevent履歴へ分離できる。
計測履歴には、記録時点の `display_status` と `baseline_conflict` を付記するだけ。

## Monitor削除・既存データ
- Monitorを削除しても記録は残す（証跡）。SQLiteはMonitor IDを再利用し得るため、Monitorが存在する間はその作成時刻以降の
  記録だけを返す。
- 既存の `inference_results` は移行しない（記録条件が違い、保存画像も無い）。新機能開始以降を正式な計測履歴とする。

## carried_forward（回転途中・見切れ中）
Drumメーターは桁の回転中に、最新Rawが6桁以下になったり `invalid_format` / `decrease_detected` で棄却されることがある。
この場合も、正式記録値は**直前の正常Confirmed値**とし、`value_source=carried_forward` で記録する。

例: 直前のConfirmed `372413.8`、記録時点のRaw `372413.0`（`decrease_detected`）→ `value=372413.8`、`raw_value=372413.0`、
`validation_status=decrease_detected`、`value_source=carried_forward`。

記録画像は「その瞬間」の実際の画像のため、`carried_forward` では正式記録値・Raw・画像（回転途中で数字が見切れている等）が
完全には一致しないことがある。これは正常な仕様で、「画像から新しい値を確定せず、直前の正常確定値を保持した」と後から
説明できるように、`validation_status`と`value_source`を残している。`usage`は、前回の定時計測値から連続していれば通常どおり
計算する（baseline conflict・reset/rebase・値の減少・前回欠損・通信異常等のnull条件は変わらない。読取不能（`display_status=read_error`）の
時間帯も、usageは`null`）。

## 記録画像（Phase 2）
1時間記録を作った時点の**元画像**と**推論オーバーレイ**を、1組だけ保存する（全推論フレームは保存しない。自動削除もしない）。

- 保存先: `<画像保存先>/<表示名>__<monitor_id>/YYYY/MM/DD/YYYYMMDD_HHMMSS_<value>_original.jpg` と `..._overlay.jpg`
  （日付と時刻は実際の記録時刻のJST）。画像保存先が未設定なら `<data_dir>/images`（自動作成）。ローカルパスとUNCに対応。
- 表示名はWindowsの禁止文字・末尾の空白/タブ・予約名をsanitizeし、`__<monitor_id>`で同名Monitorの衝突を避ける。表示名を変更しても
  過去のフォルダはrenameしない（以後の記録は新しい表示名のフォルダへ。過去の記録はDBの相対パスで辿れる）。
- 元画像はカメラフレームのJPEGをそのまま保存（再エンコードしない）。overlayと同じフレーム。映像が止まっていて古いフレームしか無い場合は保存しない（`failed`）。
- 一時ファイルへ書いてからrename。既存ファイルは上書きしない（同名があれば連番）。
- `image_status`: `ok`（有効な保存がすべて成功）/ `failed`（失敗。保存できた側のパスだけ残る。`image_error`に理由）/
  `dropped`（キュー満杯・空き容量が停止しきい値未満・保存先の障害が続いて一時停止中）/ `disabled`（元画像・overlayとも保存OFF）/
  `pending`（保存中）/ `not_saved`（Phase 1で作られた記録）。
- 画像取得: `GET /api/records/{id}/image/{original|overlay}`（保存済みファイルのみ。現在の映像は取得しない）。

### 保存先の障害と空き容量
- 画像の保存は、推論・Reading・DB記録とは別の専用スレッド（`RecordWriter`）で行う。**計測値のDB記録を先に確定**し、画像の保存に失敗・遅延・
  破棄されても、推論・Reading・計測値の記録は止まらない。
- 保存先I/Oの失敗が3回連続すると、60秒間は保存を試みず`dropped`にして、復旧後に自動再開する。
- 空き容量: 10GB未満でwarning、5GB未満で新規の画像保存を停止（既定。`/api/system/data-storage`で変更可）。停止中も計測値の記録は続く。
- 状態は `GET /api/system/data-storage/status`（UIの警告用）とログで確認できる。保存先の変更は、設定画面（Phase 4）までは`PUT /api/system/data-storage`で行う。

## Excel出力（Phase 3）

`reading_records`を正式なデータ源として、Excel(.xlsx)を出力します（`inference_results`は使いません）。
既存のCSV出力（`csv_export_log`・`/api/system/csv-*`）は**legacy（従来互換）**としてそのまま残り、新UIの主な出力はExcelです。

- API: `POST /api/records/export/excel`（`docs/06_API_REFERENCE.md`）。`monitor_ids`（空=全Monitor）と期間（`period`=今日/過去7日/任意、
  任意は`from`/`to`）を指定する。`save_to_server=false`でブラウザダウンロード、`true`でサーバーの指定フォルダへ保存する。
  どちらも同じ`excel_export_service.build_workbook()`で生成する（生成ロジックは1つ）。
- 期間: `today`=JSTの今日、`last_7_days`=今日を含む7暦日。`custom`の`to`は含まない（`recorded_at < to`）。`from >= to`は422。
  該当記録が無ければ404（`NO_RECORDS`）。記録のあるMonitorだけがシートになる。
- ファイル名: `Argus_MeterRecords_YYYYMMDD_YYYYMMDD.xlsx`（日付はJST。1日だけなら`Argus_MeterRecords_YYYYMMDD.xlsx`、期間指定なしは`..._All.xlsx`）。
  サーバー保存では既存ファイルを上書きせず、同名があれば`_2`、`_3`…を付ける。
- **1 Monitor = 1 worksheet**（1つのブック）。シート名は現在のMonitor表示名（削除済みなら記録の表示名）を基に、`: \ / ? * [ ]`を`_`へ置換、
  31文字以内、大文字小文字を区別しない重複はMonitor IDを末尾に付けて回避（空/`History`は`Monitor_<ID>`）。
- 列: 計測日時 / Monitor ID / Monitor名 / 確定値 / 前回値 / 使用量 / Raw値 / 信頼度 / validation_status / value_source / display_status /
  baseline_conflict / engine / model_id / 元画像パス / 推論画像パス。古い順。ヘッダー太字・オートフィルタ・先頭行固定。
- セル型: 確定値・前回値・使用量・信頼度は**数値**（信頼度は`0.000`）、null/値なしは**空セル**。Raw値は**文字列**（先頭0を保持。例 `0265803`）。
  計測日時は`recorded_at`をUTC→JSTへ変換した`yyyy/mm/dd hh:mm:ss`（`hour_bucket`ではなく実際の記録時刻）。
- `value_source`（confirmed / carried_forward / none）、`usage`、`validation_status`等は**DBの値をそのまま**出力する。Excel側で再判定・再計算しない。
  `carried_forward`は、記録時のRawが回転途中・見切れ・検証失敗等で確定できず、直前の正常Confirmed値を正式値として保持した記録。
- 画像: 埋め込まず、パス（`<現在の画像保存先>` + DBの相対パス）を出力する。ファイルが存在すればハイパーリンク、無ければ（保存先が不通でも）
  パス文字列のみで、Excel生成は失敗しない。1シートのハイパーリンクは65,000件まで（Excelの上限対策。超過分は文字列）。
- 保存先: `system_settings.excel_output_folder`（未設定は`<data_dir>/exports`。既定のフォルダだけ自動作成）。ローカル/UNC対応。保存先のテストは
  `POST /api/system/data-storage/test`（`target=excel`）を再利用する。
- 大量データ: DBはMonitor単位・古い順のキーセット（2,000行ずつ）で読み、XlsxWriterの`constant_memory`で1行ずつ書く（全件をメモリへ載せない）。
  ブックは常にローカルの一時ファイルへ生成し、その後でダウンロード応答/保存先へ書き出す。生成中に保存先へはアクセスしない。
- 障害の隔離: 出力は同時に1件だけ（409）。保存先の不通・権限・容量不足・60秒の無応答は、このAPIだけが503で失敗し、映像・推論・Reading・
  HourlyRecordWorker・RecordWriterには影響しない（保存先へのアクセスはタイムアウト付きの別スレッド）。
- 依存: `XlsxWriter`（書き出し）。`openpyxl`はテストでブックを開いて検証するために使う。
