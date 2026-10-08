# 1時間ごとの計測履歴（reading_records）

正式な計測記録は「**1 Monitor 1時間 1件**」です。値が変わるたびの記録ではありません（変化の履歴は
`inference_results`）。Excel出力・履歴画面・記録画像は、この記録を基にします（UI再設計 Phase 1 は記録とAPIまで）。

## 記録のタイミング

- 毎時00分（Asia/Tokyo）の計測枠（`hour_bucket`、例 `2026-10-08T14:00:00+09:00`）ごとに記録する。既定は有効
  （`PUT /api/records/settings` で無効化できる）。
- 内部は30秒ごとに計測枠を確認し、`(monitor_id, hour_bucket)` のUNIQUE制約により、何度確認しても1件。
- 計測枠の開始から**10分**を過ぎた枠は記録しない（遅れた値を定時計測にしない）。Backend再起動直後でも、10分以内なら
  `recorded_at`（実際の記録時刻）が遅れた形で記録される。
- 映像/読取が正常（正常・要確認）なら即時に値を記録。正常でない間は、立ち上がり（再起動直後など）を待つため**2分**待ち、
  それでも正常でなければ**値なし**の記録（`display_status`に理由）を作る。
- 対象は、有効（enabled）で映像ソースのあるMonitorだけ。

## 記録する値

| 列 | 内容 |
|---|---|
| `value` | 最終運用値（先頭0除去後）。映像/読取が正常でない時間帯は `null` |
| `raw_value` | 元の桁列（先頭0を含む）。runtime稼働中のみ |
| `previous_value` | 前回（1時間前の枠）の定時計測値。前回の記録が無い、または値なしなら `null` |
| `usage` | 今回 − 前回の定時計測値（Decimalの文字列）。下記の場合は `null` |
| `confidence` / `validation_status` / `display_status` | 信頼度、検証status、記録時点の表示状態（正常/要確認/読取不能/通信異常 等） |
| `baseline_conflict` | 記録時点でbaseline conflictの警告中か |
| `engine` / `model_id` / `monitor_name` | 記録時点のengine、model、Monitor表示名のスナップショット |
| 画像列 | `original_image_path` / `overlay_image_path` / `image_status` / `image_error`（Phase 2で保存。現在は `image_status=not_saved`） |

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
