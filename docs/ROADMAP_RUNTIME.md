# Runtime / 前処理ロードマップ

## 現在の実装

- Monitor単位のVideoReader、LatestFrameBuffer、再接続Runtime
- Runtime diagnostics と stale frame 判定
- 正規化ROIの保存とEditor（ROI PUTは対象Monitorのruntimeを再構成し、稼働中の推論へ即時反映）
- 前処理PreviewとMonitor単位のJSON保存、実画像への適用（grayscale/threshold/invert/brightness-contrast等）
- InferenceEngine（Ultralytics YOLO / EasyOCR / Tesseract）の実推論、ModelRegistryによるモデルcache/reuse、DeviceResolver
- 推論結果の座標復元（ROI/前処理を経た検出bboxをfull-frame座標へ変換）とoverlay JPEG配信
- 推論結果のLatestResult/InferenceResult保存（値変化時 + heartbeatでの履歴保存）とDashboard/Detail表示
- Diagnostics API（`GET /api/system/inference`）とFrontend Device選択肢の実環境連動
- Backend base CI（pytest）とFrontend build CI、重いAI依存のみを使う手動Smoke Test workflow

「Validate Real Camera and Inference Engines End-to-End」で実ultralytics/実easyocr/実tesseract・実カメラ・実GPU（環境がある場合）による検証を実施済み。

## Migration導入タイミング

現在のMVPでは、SQLite起動時に不足カラムを限定的に追加しています。
今後、テーブル追加・カラム変更・データ変換が複数発生する段階では、起動時ALTERではなくAlembic等のmigration管理へ移行します。

## 次に実装する範囲

- Argus専用の高精度な数字検出モデルの整備（現状は外部持ち込みモデルでのSmoke Test止まり。「Digit model required」）
- Alert、グラフ、履歴分析
- Engine/Device変更時に対象Monitorの映像取得スレッドまで止めずに再構成する、より無停止に近いRuntime再構成方式の検討
