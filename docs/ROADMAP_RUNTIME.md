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
- Raw Reading→Confirmed Readingの時系列安定化（`backend/reading/`、多数決/連続一致）とValidation（monotonic/rate/桁数/rollover）
- Confirmed Reading中心のLatestResult/履歴保存（Raw推論結果を直接DBへ保存しない）、Reading Diagnostics API
- Argus専用数字検出モデルの学習（`yolo_pipeline_studio`の既存Training/Evaluation機能を利用）とFull Reading Exact Match中心の評価（`backend/evaluation/`、`backend/scripts/evaluate_meter_model.py`）、role付きModel Registry（`data/models/registry.json`、`GET /api/system/models`）、開発用データ収集モード

「Validate Real Camera and Inference Engines End-to-End」で実ultralytics/実easyocr/実tesseract・実カメラ・実GPU（環境がある場合）による検証を、「Improve Meter Reading Accuracy and Temporal Stabilization」でRaw/Confirmed分離とTemporal Stabilizationを、「Build and Evaluate Production-Ready Meter Digit Detection Model」でArgus専用モデルの学習・評価・Model Registryを実施済み（詳細: `docs/METER_DIGIT_MODEL_EVALUATION.md`）。

## Migration導入タイミング

現在のMVPでは、SQLite起動時に不足カラムを限定的に追加しています。
今後、テーブル追加・カラム変更・データ変換が複数発生する段階では、起動時ALTERではなくAlembic等のmigration管理へ移行します。

## 次に実装する範囲

- Argus専用数字検出モデルの追加データ収集・再学習（学習139枚・Test 21枚と小規模なため"Production Candidate"止まり。詳細: `docs/METER_DIGIT_MODEL_EVALUATION.md`）
- 機械式カウンター方式メーター（Domain B）向けの専用データ収集・学習
- Alert、グラフ、履歴分析（Confirmed Readingのみを見る構造は用意済み）
- Engine/Device変更時に対象Monitorの映像取得スレッドまで止めずに再構成する、より無停止に近いRuntime再構成方式の検討
- 実際の物理メーターを使ったConfirmed値の長時間安定性検証（開発環境に物理メーターを継続設置できないため未実施）
