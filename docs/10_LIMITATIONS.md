# Limitations

READMEの「未実装・既知の制限」とソースコードから確認できる事項をまとめます。

（2026-08 追記: YOLO/EasyOCR/Tesseractの実推論、ROI編集、前処理編集、実推論結果・履歴は
「Validate Real Camera and Inference Engines End-to-End」で実ライブラリ・実モデルにより
検証済み。「Improve Meter Reading Accuracy and Temporal Stabilization」でRaw Reading→
Confirmed Readingの時系列安定化・Validationを追加。以前ここに記載していた「未実装」は
実態と合っていなかったため更新した。）

## 未実装

- Argus専用に学習された高精度な数字検出モデル（現状は外部持ち込みモデルのSmoke Test止まりで、精度評価・追加学習は未実施。「Digit model required」）
- Alert、推論結果のグラフ表示・履歴分析（Confirmed Readingのみを見る構造は用意済み）
- `datetime.utcnow()`のtimezone-aware化（DB層のdatetime列がnaive前提のため、部分的な修正はnaive/aware比較エラーの原因になりうる。今回のscopeでは見送り）

## 既知の制限

- カメラ一覧はOpenCVで0〜4番を探索
- URL認証はOpenCV接続用に一時URL形式へ変換するため、機器やOpenCV buildによっては別途対応が必要
- `ARGUS_SECRET_KEY`未設定時は開発用固定キー
- Windows DPAPIの実装は確認できず、現在のSecretStoreはFernetを使用
- WebSocket実装は確認できない
- Migration設定は確認できない（起動時の限定的なALTER TABLEで対応）
- Frontendの自動テスト、Lint、Formatter設定は確認できない
- CI（`.github/workflows/ci.yml`）はBackend base依存＋pytest（`optional_inference`/`hardware`マーカーは除外）とFrontend buildのみ。重いAI依存を使ったSmoke Testは`inference-smoke.yml`（手動実行）に分離しており、GPU/実カメラに依存するテストはCI上では実行できない
- Engine/Device変更はROI PUTを含め対象Monitorのruntime（映像取得スレッド含む）を再構成する方式のため、切替中に該当Monitorの映像へ一瞬の断が生じうる（他Monitorには影響しない）
- 実際の物理メーター（積算ガスメーター等）でのConfirmed値の長時間安定性は未検証（開発環境に物理メーターが無いため）。合成シーケンスによる単体テストと、実カメラ・実YOLOでのNO_DETECTION連続時の`no_reading`遷移は実機で確認済み
- `min_confidence`は「投票から除外する」用途ではなく「Confirmed/LowConfidenceの判定基準」としてのみ使用する（シンプルさを優先した設計判断）

## ソース上で追加確認が必要な事項

- `backend/app/models/video_source.py`では`encrypted_password`の型付き属性宣言が同一名で2回記載されています。
- `monitor_service.py`は`UrlHistory`に`encrypted_password`がある前提の分岐を含みますが、確認した`UrlHistory`モデルにはその属性宣言がありません。

上記は修正せず、現状の確認事項として記載しています。

