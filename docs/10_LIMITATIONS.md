# Limitations

READMEの「未実装・既知の制限」とソースコードから確認できる事項をまとめます。

## 未実装

- YOLO実推論
- EasyOCR実推論
- Tesseract実推論
- ROI編集
- 前処理編集
- 実推論結果、推論履歴、アラート
- GPU実推論

## 既知の制限

- カメラ一覧はOpenCVで0〜4番を探索
- URL認証はOpenCV接続用に一時URL形式へ変換するため、機器やOpenCV buildによっては別途対応が必要
- `ARGUS_SECRET_KEY`未設定時は開発用固定キー
- Windows DPAPIの実装は確認できず、現在のSecretStoreはFernetを使用
- WebSocket実装は確認できない
- CI/CD設定は確認できない
- Migration設定は確認できない
- Frontendの自動テスト、Lint、Formatter設定は確認できない

## ソース上で追加確認が必要な事項

- `backend/app/models/video_source.py`では`encrypted_password`の型付き属性宣言が同一名で2回記載されています。
- `monitor_service.py`は`UrlHistory`に`encrypted_password`がある前提の分岐を含みますが、確認した`UrlHistory`モデルにはその属性宣言がありません。

上記は修正せず、現状の確認事項として記載しています。

