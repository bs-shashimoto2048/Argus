# Runtime / 前処理ロードマップ

## 現在の実装

- Monitor単位のVideoReader、LatestFrameBuffer、再接続Runtime
- Runtime diagnostics と stale frame 判定
- 正規化ROIの保存とEditor
- 前処理PreviewとMonitor単位のJSON保存
- InferenceEngine、ModelRegistry、DeviceResolverの拡張可能な雛形

## Migration導入タイミング

現在のMVPでは、SQLite起動時に不足カラムを限定的に追加しています。
今後、テーブル追加・カラム変更・データ変換が複数発生する段階では、起動時ALTERではなくAlembic等のmigration管理へ移行します。

## 次に実装する範囲

- Ultralytics YOLO実推論
- EasyOCR / Tesseract実推論
- 推論Schedulerと結果保存
- Alert、グラフ、履歴分析
