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
| `previous_value` | 前回（1時間前の枠）の定時計測値。差分の基準にできる前回値が無い場合（前回recordが存在しない・値なし・信頼できない・連続性が切れた）は、今回が信頼できれば `null`（再開点。エラーではない。画面は「--」、Excelは空欄） |
| `usage` | その時刻に保存された正式値 − 直前1時間の正式値（Decimalの文字列。値の由来 confirmed / carried_forward は問わない）。下記の場合は `0` / `null` |
| `confidence` / `validation_status` / `display_status` | 信頼度、検証status、記録時点の表示状態（正常/要確認/読取不能/通信異常 等） |
| `baseline_conflict` | 記録時点でbaseline conflictの警告中か |
| `engine` / `model_id` / `monitor_name` | 記録時点のengine、model、Monitor表示名のスナップショット |
| 画像列 | `original_image_path` / `overlay_image_path`（画像保存先からの相対パス）/ `image_status` / `image_error`（下記「記録画像」） |

### 使用量（usage）の計算
usage は **その時刻に保存された正式値 − 直前1時間の正式値** です。正式値の由来（`confirmed` / `carried_forward`）や `baseline_conflict` では区別しません。
例: 18:00 = 100 / 19:00 = 105（Raw異常で正式値105を保持した `carried_forward`）→ 19:00 の usage = 5。105 のまま続く 20:00 以降は 0。

**対象になる正式値**: 正式値（`numeric_value`）があり、映像・読取が稼働中（`display_status` が normal / warning）であること。
手動修正済み（`correction_count > 0`）は、運用者が画像等で確認した値なので `display_status` によらず対象。

**連続計測区間の開始点（再開点）**: 今回が対象の正式値で、差分の基準にできる直前値が無いとき、`previous_value=null`、`usage=0`（新しい区間の最初の点）。
基準にできない直前値 = 直前1時間のrecordが存在しない（計測開始・長時間停止後の再開） / 直前recordに正式値が無い / 直前が通信異常・read_error等で連続性を保証できない /
直前以降に運用者のresetまたは別値へのrebaseがあり連続性が切れた。以前の記録へは遡りません。読取失敗ではないため、グラフは赤い×を出さず、Y=0の通常のプロットになります。

**`usage=null` になる場合**: 今回に正式値が無い / 今回が通信異常・read_error等で対象外 / 正式値が直前より減少した（`previous_value` は直前の値）。

rebaseは、新しい値が前後どちらかの正式値と一致する場合（運用者が確認した値への再設定）は連続性を壊しません。
設定変更（decimal_position / expected_digits）に伴うbaselineの自動クリア（`auto_semantic_reset`）も、正式値が変わらないため切りません。

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
説明できるように、`validation_status`と`value_source`を残している。`usage`は、carried_forwardでも正式値同士の差で計算する（上記「使用量（usage）の計算」）。

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

### carried_forward の例（Raw棄却中でも、それ以前に確定済みの値を保持）

07:00 の正式値が `215836`、07:00〜08:00 の間に正常Confirmed `215858`、08:00 の瞬間のRawが `0215850`（`decrease_detected`）だった場合、
08:00 の記録は `value=215858` / `value_source=carried_forward` / `raw_value=0215850` / `validation_status=decrease_detected` / `usage=22` になります。
「08:00時点の最新Rawは棄却したが、それ以前に正常確定済みの215858を保持した」という意味で、不具合ではありません。

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
- 列（利用者向けの日本語見出し）: 計測日時 / モニターID / モニター名 / 確定値 / 前回値 / 使用量 / AI読取値 / 信頼度 / 読取結果 / 採用方法 / 状態 /
  基準値不一致 / 読取エンジン / 使用モデル / 元画像パス / 推論画像パス（以降の証跡・修正の列は後述）。古い順。ヘッダー太字・オートフィルタ・先頭行固定。
- 「読取結果」（validation_status）・「採用方法」（value_source）・「状態」（display_status）・「基準値不一致」（baseline_conflict: あり / なし）のセルは、
  UIと同じ日本語表記で出力します（`readingLabels.ts` / `records.ts`と一致。Excel専用の独自表現は作りません。未知の値は内部値のまま）。
  「読取エンジン」「使用モデル」は技術情報のため内部値のままです。
- セル型: 確定値・前回値・使用量・信頼度は**数値**（信頼度は`0.000`）、null/値なしは**空セル**。Raw値は**文字列**（先頭0を保持。例 `0265803`）。
  計測日時は`recorded_at`をUTC→JSTへ変換した`yyyy/mm/dd hh:mm:ss`（`hour_bucket`ではなく実際の記録時刻）。
- 「Monitor名」セルは、先頭・末尾の空白/制御文字（タブ・CR・LF等）だけを除いて表示する（内部のスペースは維持。DBの`monitor_name`スナップショットは変更しない）。
- `to`は排他的（`2026-10-08`は`2026-10-08 00:00`）。終了日を含めたいときは呼び出し側（Phase 4 UI）が翌日0:00を渡す。Backendは補正しない。
- 確定値・使用量等は**DBの値をそのまま**出力する（読取結果・採用方法・状態は表記だけを日本語にする）。Excel側で再判定・再計算しない。
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

## 証跡の整合性: 1推論tick = 1 immutable snapshot

定時計測recordの値・Raw・信頼度・判定・画像は、**同じ推論tick**のものでなければ正式な証跡になりません。以前は、recordの作成中も推論が続くため、
Raw・validation_status・正式値と、元画像・overlayが別のtickのものになる可能性がありました。次の仕組みで、新しい記録からこれを保証します。

- `InferenceScheduler`は、1回の推論（Engine推論 → overlay生成 → `ReadingStabilizer.update()` → 運用値の保存）がすべて終わったあとに、そのtickの
  情報だけを`InferenceRecordSnapshot`（`backend/runtime/record_snapshot.py`、frozen dataclass）にまとめ、**丸ごと差し替え**ます（Lockつき）。
  内容: 推論時刻・フレーム取得時刻・元画像JPEG（推論に使ったフレームそのもの）・overlay JPEG・Raw値/Rawの信頼度/エラー・読取判定・合意候補・一致数・
  正式値/正式値の信頼度/確定時刻（`ResultStore`が保存した運用値）・engine/model/処理時間・baseline値/epoch/conflict。
- `HourlyRecordWorker`（`record_due`）は、記録ごとに`get_record_snapshot()`を**1回だけ**取得し、その同じsnapshotだけから`reading_records`（`raw_value`・
  `raw_confidence`・`validation_status`・`value`・`confidence`・`baseline_conflict`・`engine`/`model_id`・`inference_at`）と画像ジョブ（元画像・overlay）を作ります。
  その後に`LatestResult`などを読み直さないので、画像保存が遅れていても、推論が次のtickへ進んでも、記録の内容は変わりません。
- `recorded_at`は定時計測をDBへ保存した時刻、**`inference_at`は証跡snapshotの推論時刻**（例: 08:00:00.243に行われた実推論）で、別の値です。`hour_bucket`は従来どおりです。
- `confidence`は**正式値側**の信頼度、`raw_confidence`は**記録snapshotの最新Raw側**の信頼度です。`carried_forward`では別のtickの値になるため、UIの詳細Drawerでも分けて表示します
  （「正式値の信頼度」「最新推論値の信頼度」）。
- 推論が止まって古い（10秒超）snapshotは使いません（従来の経路で記録し、`inference_at`は空）。通信異常等のMonitorは従来どおり値なしの記録です。
- **既存のrecord・保存画像は書き換えません**。この仕組みの導入前に作られた記録（`inference_at`が空 / API`snapshot_consistent=false`）は
  「厳密な同一tick保証が無かった既存データ」としてそのまま保持し、画像やRawを後から推測で補正しません。

## 読取値（正式値）の手動修正と監査履歴

- **修正できる記録**: `value_source=carried_forward`（UI: 前回確定値を保持）、または基準値競合中の記録（`baseline_conflict=true`、または`validation_status`が
  `decrease_detected`/`rate_exceeded`）だけ。通常のconfirmedな記録は修正できません（409）。履歴の詳細Drawerに、対象記録の場合だけ「読取値を修正」を表示します。
- **修正ダイアログ**: 記録日時・正式値・最新Raw・Rawの信頼度・保存したoverlay画像・読取判定・値の由来・現在の読取基準値と競合候補を見ながら、修正後の値・修正理由（必須）・
  操作者（必須）を入力します。「最新推論値 〇〇 を入力」ボタンは入力欄を埋めるだけで、自動確定はしません。
- **変更するもの**: `value`/`numeric_value`と、それに連動する`usage`/`previous_value`だけ。**元証跡（`raw_value`・`raw_confidence`・`validation_status`・`value_source`・
  画像・`inference_at`）は変更しません**。`value_source`は`manual_corrected`へ上書きせず、`carried_forward`のまま、`correction_count`/`original_value`/`corrected_at`/`corrected_by`で修正済みを表します
  （UI: 「前回確定値を保持 → 手動修正済み」、一覧に「修正済み」badge）。
- **同じ値への補正**: 修正後の値が現在の正式値と同じでも受け付ける。「画像等で確認し、保持している正式値が正しい」と運用者が明示的に確認した監査記録になり、
  `reading_record_corrections` に `old_value == new_value` の履歴が追加され、`correction_count` が増え、「修正済み」(手動修正マーカー)になる。元証跡は変えず、baselineも自動では変更しない（明示した場合のみ）。
- **補正値の安全確認（2段階確認）**: 値を変える補正で、補正値が **直前1時間の正式値 / 次の1時間の正式値 / 現在の読取基準値** に対して3倍超・1/3倍未満（10倍・1/10倍＝桁落ち・小数点位置の誤りを必ず含む）、
  または `max_rate_per_minute` 設定時に1時間あたりの許容増加量（×60）を超える場合は、保存せず `409 CORRECTION_FORCE_REQUIRED`（`details.reasons` に理由）を返す。
  画面は「前後の正式値から大きく乖離しています。桁落ち・小数点位置を確認してください。」を表示し、確認チェック後に `force=true` で再送した場合だけ保存する（監査履歴の `context.safety` に確認した理由が残る）。
  hard blockではない（メーター交換・reset等の正当な大変動があり得るため）。比較できる前後の正式値・基準値が無い場合、および同値補正は確認を要求しない。判定は `expected_digits` の完全一致ではない（先頭0を除去した正式値では桁数が変わるMonitorがあるため）。
- **「最新推論値を入力」の制限**: 読取判定が `invalid_format` / `no_reading` / `pending` 等、値の形式が成立していないRawは自動入力できない（「このRawは桁数・形式判定で不採用のため、自動入力できません。画像を確認して正式値を入力してください。」）。
  `decrease_detected` / `rate_exceeded` は形式が正常なので自動入力できるが、「基準値または変化率判定で不採用です。画像確認後に使用してください。」と警告する。
- **usageの再計算**: 修正した記録と後続の `usage` / `previous_value` を、上記「使用量（usage）の計算」の規則で順に再評価する（例: 07:00=215836、08:00=215858→215850、09:00=215865 → 08:00のusage 22→14、09:00のusage 7→15）。
  後続の値は書き換えない（必要なら個別に修正）。連続区間の一括補正は別機能として未実装です。
- **監査履歴**: `reading_record_corrections`（追記のみ。複数回修正しても全履歴が残る）。old/newの値とusage、理由、操作者、修正時点の元証跡のコピー、client_host、context（次の記録のusage変化など）。
  `GET /api/records/{id}/corrections`で新しい順に取得できます。
- **baselineとの関係**: 履歴の修正だけでは、現在の読取基準値（runtimeのbaseline）を変更しません。修正ダイアログの「現在の読取基準値もこの値へ再設定する」（既定OFF、現在も競合が続いている場合に表示）を
  ONにしたときだけ、既存のrebase処理を呼びます（force要求・検証・baseline側の監査履歴はそのまま。修正の監査履歴にも実施有無を残します）。rebaseが失敗した場合、記録の修正も行いません。
- **Excel**: 確定値・使用量は修正後の正式値です。末尾に`AI信頼度`/`AI読取時刻`/`修正あり`/`修正回数`/`最終修正日時`/`初回値`の列を追加しました（元証跡の列は変わりません）。複数回修正した記録でも、行には最終の確定値・修正回数・最終修正日時・最初の修正前の確定値（初回値）だけを出し、途中の修正値は出しません（全履歴は`reading_record_corrections`に残ります）。「採用方法」は、修正済みの記録ではUIと同じ「運用者が確認・修正」になります。

## 一覧の順序

`GET /api/records`は、`hour_bucket` DESC → Monitorの表示順（`display_order` ASC） → `monitor_id` → `id` の安定した順序で返し、`limit`/`offset`（段階読み込み）もこの順序で行います
（同じ計測枠の行が取得境界をまたいでも連続し、すでに表示している行が動かないため）。

## usageの再計算（手動修正後・バックフィル）

- 手動修正後は、修正した記録と後続の `previous_value` / `usage` だけを時系列順に再計算して保存する（値・証跡は書き換えない）。
  直後の記録の `previous_value` / `usage` が変わらなければそこで止める。ただし同じ値のcarried_forwardが連続している間は、旧規則で保存されたusageが残っている可能性があるため先へ進む。
  応答の `recomputed_records` に再計算した記録の一覧が入る。
- 元の証跡（`value` 以外の `raw_value`・`raw_confidence`・`validation_status`・`value_source`・`baseline_conflict`・画像・`inference_at`）は、再計算でも変更しない。
- Dashboardは、修正の成功後に履歴とグラフをBackendから取り直す（usageをFrontendで仮計算しない）。
- 既存recordのusage（旧仕様で保存された値を含む）は自動では書き換えない。`backend/scripts/backfill_reading_usage.py` を、Monitor・日付を指定して実行した範囲だけが更新される（dry-runが既定。`--apply` の前にDBをバックアップする）。

## 運用メモ(reading_records.memo)

- 記録単位の自由テキスト(最大500文字・前後の空白は除去・空文字は削除=NULL)。AI読取値・正式値・usage・修正履歴・baselineとは独立で、メモを編集してもそれらは変わりません。
- 更新は専用API `PATCH /api/records/{id}/memo`(body: `{"memo": "..."}`)。存在しない記録は404、501文字以上は422。`GET /api/records` / `GET /api/records/{id}` の応答に `memo` を含みます。
- 起動時に `reading_records.memo`(VARCHAR(500) NULL)を `ALTER TABLE ADD COLUMN` で追加します(既存の記録は書き換えず NULL)。
- Excel出力(22列)には含めません(別途判断)。
