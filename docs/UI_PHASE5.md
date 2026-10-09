# UI再設計 Phase 5: Monitor Detailのタブ化・履歴UIの操作改善・画面揺れ防止

**Backendの変更はありません**（Frontendのみ）。推論・Reading・baselineのロジックにも触れていません。

## 計測履歴UI（Dashboard下部 / 履歴・データ / Monitor DetailのHistoryタブ）

- **Monitorはプルダウン**（「すべてのモニター」または1台）。変更した瞬間に履歴を再取得します（「適用」ボタンなし）。Excel出力は現在のフィルタをそのまま使うので、複数Monitorをまとめたい場合は「すべてのモニター」を使います。
- **表示期間は3択**: 今日 / 過去7日 / 任意期間（選択中のボタンは強調表示）。選択した瞬間に切り替わります。
- **任意期間のときだけ**期間選択BOX（開始日 ～ 終了日）を表示します。開始日・終了日が有効（開始≦終了）になった時点で即時に更新します。APIの`to`は排他的なままで、UIの終了日`2026/08/26`は`2026-08-27T00:00:00+09:00`として渡します（Backendは補正しません）。
- **履歴表はヘッダー固定のスクロール式**: 1つの`table`（`table-layout: fixed` + `colgroup`）の中でヘッダーを`position: sticky`にして固定し、表の中だけが縦スクロールします。列位置はずれず（`scrollbar-gutter: stable`）、狭い画面では表の内部だけが横スクロールします（ページ全体の横スクロールなし）。表のエリアは常に同じ高さです（Dashboardは固定、履歴・データ画面は画面の高さに合わせる）。読込中・0件・多数件でも高さが変わりません。

## Dashboard

- ページタイトル「ダッシュボード」は置きません（上部ナビゲーションにあるため）。
- **[＋ モニター追加]の右隣に、同じ操作グループとして Monitoring 表示**（`● Monitoring | 5 FPS | ⚙`）を置きます。両者は同じ高さ（40px）・角丸（8px）・フォントサイズで、Monitoringは白地の枠線つきコンパクトコントロール（操作ボタンではなく状態表示なので、色は青ではなく白）。●は稼働中のMonitorがあれば緑、FPSは現在の表示FPS設定、⚙は既存のDashboard設定です。hover / focusの表現も揃えています。

## 画面揺れ防止

- `html { scrollbar-gutter: stable }`（scrollbarの出現・消滅で横にずれない）、`body { overflow-x: hidden }`。
- 数値（確定値・Raw・信頼度・使用量等）は`font-variant-numeric: tabular-nums`。
- Monitorカードは、通知欄（前回確定値を保持・基準値conflictのバッジ）の高さを常に確保し、値の桁数・バッジの有無・状態で高さが変わりません。ライブ画像は固定高さ、Drawerの記録画像は`aspect-ratio: 16 / 9`で、読込前後でサイズが変わりません。
- 実ブラウザ（1366×768 / 1920×1080）で、30秒間の更新中のlayout shiftは0、カード高さ・履歴領域の高さ・ページ幅は不変であることを確認しています。

## Monitor Detail（`/monitors/:id`）のタブ

`?tab=history|settings|diagnostics`で直接開けます（既定はMonitoring）。編集中のSettingsの入力値は、タブを切り替えても失われません。

| タブ | 内容 |
|---|---|
| **Monitoring** | 日常監視用。ライブ画像/推論オーバーレイ、確定値・前回値・信頼度・状態、Raw（最新・未確定）、engine、model、最終更新、baseline、conflict、警告。**危険な設定操作は置きません** |
| **History** | このMonitorの計測履歴（Monitor選択なし、今日/過去7日/任意期間、記録画像Drawer）。Dashboard/履歴画面と同じコンポーネント |
| **Settings** | 基本情報、映像Source、推論Engine/Model、前処理、ROI、読取安定化（Reading settings）、保存、Danger Zone（削除）。既存の機能・保存処理はそのまま |
| **Diagnostics** | 技術確認用。Engine/Model・映像Runtime・映像取得fps・推論エラー、推論オーバーレイ、推論入力、Raw・検証・基準値・合意候補・conflict、Pipeline診断。末尾に**「管理操作」**（読取基準値の再設定/リセット）を通常の設定と分けて配置 |

## baseline の reset / rebase（管理操作）

Diagnosticsタブの「管理操作」にあります。**再設定（rebase）は確認ダイアログ**で、現在の基準値・最新のRaw・合意候補・指定する値・理由・操作者を確認してから実行します。Backendのforce要求（最新のRaw合意値と大きく異なる値）・入力検証・監査履歴は変更していません。

## /api/cameras

- 以前は、Monitor Detailを開くだけで`SourceSettings`が`/api/cameras`を呼んでいました。**現在は呼びません**（どのタブを開いても0回）。
- 現在設定されているsourceは、カメラ検出なしで表示されます（「現在の設定: Camera N」/ URL）。
- 検出できるカメラ一覧は、「カメラ選択（検出）」「再スキャン」を押したときだけ取得します。検出に失敗しても現在の設定は保持されます。

## Monitor表示順の並べ替え（追加仕様）

Dashboardのカードの順番を、**モニター管理（`/monitors`）から変更して永続化**できます。

- **DB**: `monitors.display_order`（整数）。既存Monitorは起動時にid昇順の順位（id=2,3,4 → 0,1,2）で補完（設定済みの値は変更しない）。新規Monitorは末尾（最大+1）。削除による欠番は詰め直しません。
- **一覧の順序**: `GET /api/monitors`は`display_order ASC → id ASC`（未設定は最後）。Dashboard・モニター管理・履歴のMonitor選択は、APIの順序をそのまま使います（Frontendで独自にソートしない）。Excelのworksheet順も現在の表示順に揃います（値・意味は変更なし）。
- **API**: `PUT /api/monitors/order`（`{"monitor_ids": [4, 2, 3]}`）。重複ID・存在しないIDを拒否し、全Monitorの指定を必須とし、**1 transaction**で更新します（`docs/06_API_REFERENCE.md`）。
- **UI**: 行のドラッグ&ドロップ、または各行の↑↓ボタン（キーボード/クリックで操作可）。**操作の完了時に自動保存**します（保存ボタンなし）。保存中は「保存中...」、成功すると短時間「保存済み」。保存中は楽観的に新しい順を表示し、**失敗したときは元の順へ戻して**エラーを表示します（一覧が更新されていた場合は再読み込みして同期）。定期更新の結果で保存中の順序が一瞬戻ることはありません。
- 履歴データ（`reading_records`等）は変更しません。表示順は現在のUI表示順だけの設定です。

## 既知の制約

- 診断の「processing time（推論処理時間）」は、Backendのdiagnostics APIが返していないため表示していません（映像取得fps・最新フレーム経過秒は表示）。
- Monitorカードの「単位」は、Monitorに単位の設定項目が無いため表示していません。
- carried_forwardの連続時間の集計は未実装です。
- 画像保存先の変更後に旧画像を参照できない課題は残っています（Phase 4で警告を追加済み）。
