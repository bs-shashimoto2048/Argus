# Testing

## 存在するテスト

`backend/tests/test_monitors.py`に次の2テストがあります。

- `test_monitor_crud`: Monitor作成、取得、更新、削除
- `test_validation_and_url_error`: Monitor名のvalidationと空URL接続確認エラー

`backend/tests/conftest.py`は`backend`をPython pathへ追加し、FastAPI `TestClient`を利用します。

## 実行方法

専用のpytest scriptや設定ファイルは確認できません。テスト依存として`pytest`、`httpx`が`backend/requirements.txt`にあります。

リポジトリ内に固定されたテスト実行コマンドは確認できません。

## カバレッジ

カバレッジ設定、coverage依存、coverage用コマンドは確認できません。

## Frontendテスト

Frontend用のテストファイルとtest scriptは確認できません。`npm run build`はTypeScript buildとVite buildを実行しますが、テストではありません。

