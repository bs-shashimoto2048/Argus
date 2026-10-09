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

Frontendのテストは`frontend/src/test/`にあり、`cd frontend; npm test`（vitest + jsdom + Testing Library、fetchをモックするため実Backend・実DBは使わない）で実行します（UI再設計 Phase 4で追加。CIのfrontend jobでも実行）。`npm run build`はTypeScript buildとVite buildを実行しますが、テストではありません。

