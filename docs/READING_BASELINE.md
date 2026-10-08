# 読取基準値（monotonic baseline）と reset / rebase（Issue #40）

積算メーターでは、確定値が前回より減らないこと（`monotonic`）と、変化量が上限以内であること
（`max_rate_per_minute`）を、**前回確定値（baseline）** と比較して検証します。このbaselineを永続化し、
誤値が確定して固着した場合に運用者が明示的に復旧できるようにしたものです。

## 背景（実機で起きたこと）

- 以前はbaselineがメモリ上にしかなく、Backend再起動・設定保存（Scheduler再構築）のたびに空になりました。
  このため、誤読の減少が検証をすり抜けて確定しても、記録は残りませんでした。
- 逆に、誤った高い値が確定すると、以降の正しい値はすべて`decrease_detected`として**静かに棄却**され、画面は
  正常に見えたまま固着しました（Digital 7桁で `0265759` が誤確定し、実値 `0265754` が約7時間棄却された）。
  このとき復旧できたのは、偶然の再構築でbaselineが空になったためだけでした。

baselineを永続化すると、この「偶然の復旧」がなくなります。そのため永続化・reset・rebase・conflict可視化・監査履歴を
同時に導入しています。**低い値の自動採用はしません。**

## 仕組み

| 項目 | 内容 |
|---|---|
| 永続化 | `reading_baselines`（Monitorごとに1行）。CONFIRMEDのときだけ書き込む（LOW_CONFIDENCE・棄却されたstatus・`reading.enabled=false`は対象外） |
| 復元 | Scheduler構築時（Backend再起動、stop/start、engine/model/ROI/前処理/reading設定の保存）にDBから復元。Raw windowと連続失敗回数は初期化 |
| 既存Monitor | baseline行なしで開始（`latest_results.value`から自動では作らない）。最初のCONFIRMEDで初回baselineを作る |
| semantic fingerprint | `decimal_position`/`expected_digits`が保存時と異なる場合は数値の尺度が変わるため、復元せず自動クリアして監査（`auto_semantic_reset`）に残す |
| 先頭0 | baselineの比較は数値（`numeric_value`）で行う。確定値の整数部の先頭0除去（全Monitor共通）の影響を受けない |
| epoch | reset/rebase/自動クリアのたびに増える世代番号。操作前の世代で計算されたConfirmedがbaselineを上書きしない |
| 表示値 | reset/rebaseは`latest_results`（Dashboardの現在値）を直接書き換えない。次の正常なConfirmedで自然に更新される |

## conflict（固着の疑い）の可視化

合意候補（`required_matches`を満たした値）が `decrease_detected` または `rate_exceeded` で棄却され続けている状態をconflictとして
追跡します（候補・回数・開始時刻）。**5分以上**続くと `baseline_conflict` となり、Dashboardのカードと、Monitor詳細の
警告・「読取基準値」に次のように表示されます（値は先頭0除去後）。

> 基準値 265759 より小さい読取 265754 が3時間12分続いています

- 棄却が途切れても60秒以内に再発すれば継続扱い。Scheduler再構築をまたいでも、直前のconflictが10分以内なら継続します。
- しきい値は `backend/reading/baseline.py` の定数（`CONFLICT_ALERT_SECONDS` など）で変更できます。
- 診断（Monitor詳細の推論デバッグ）には、検証status・基準値・合意候補・conflictが表示されます。Rawは元の桁列です。

## 復旧の手順（Monitor詳細 > 読取基準値）

1. **実メーターの表示を確認する**（推論オーバーレイと実表示を見比べる）。
2. 主な手段: **基準値を指定して再設定（rebase）**。実メーターで確認した値、理由、操作者を入力する。
   - `expected_digits`/`decimal_position`で検証される（先頭0の有無は問わない）。
   - 最新のRaw合意値と大きく離れている場合（最下位桁の10単位超）は警告され、確認のチェックを入れないと実行できない。
3. 補助的な手段: **基準値をリセット**。次に正常に確定した値が新しい基準になる（メーター交換・リセット時、
   新しい値が分からない場合）。読取が不安定なときは、誤読を新しい基準にしてしまう恐れがあるためrebaseを推奨。
4. 理由と操作者は必須（認証が未導入のため操作者は自己申告。`client_host`も記録）。操作は監査履歴に残る
   （旧基準値・新基準値・理由・操作者・時刻・その時点の合意候補/conflict/設定）。

## 設定ごとの扱い

| 設定 | 扱い |
|---|---|
| `monotonic=false` | 減少を検証しないためconflictにならない（baselineは`max_rate_per_minute`の基準として保持） |
| `reading.enabled=false` | baselineは永続化せず、reset/rebaseは409 |
| `allow_rollover=true` | 減少が許容されるためconflictにならない。メーター交換にresetは不要 |

## API

`docs/06_API_REFERENCE.md`の「Reading」を参照（`/reading/baseline`、`/reset`、`/rebase`、`/events`）。

## 既知の制約

- 操作者は自己申告（認証導入時に置き換える）。
- 監査履歴は`monitor_id`で保持する。SQLiteがIDを再利用した場合に備え、Monitorが存在する間はその作成時刻以降のイベントだけを返す。
- conflictのDB書込みは、状態の変化時または30秒ごと（毎推論tickでは書かない）。
- LOW_CONFIDENCEで受理された値は、メモリ上の判定では従来どおりbaselineになるが、永続化はしない（再起動後は直前のCONFIRMEDに戻る側＝緩い側）。
