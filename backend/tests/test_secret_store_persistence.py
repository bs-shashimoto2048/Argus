"""保存済み認証情報(Basic認証password)がBackend再起動後も利用できることを確認する
(Issue #14: Backend restart後も保存済みsecretが利用できることをテストする)。

`LocalSecretStore`は`ARGUS_SECRET_KEY`未設定時、固定の決定的keyから鍵導出するため、
プロセスを跨いでも同じ暗号化文字列を復号できる必要がある。ここでは新しい
`LocalSecretStore`インスタンス(=プロセス再起動を模擬)で復号できることを検証する。
"""
from __future__ import annotations

import pytest

from app.core.security import LocalSecretStore
from app.services.secret_store import decrypt, encrypt

pytestmark = pytest.mark.unit


def test_encrypted_password_survives_new_secret_store_instance():
    """encrypt()で暗号化した文字列を、新規に生成したLocalSecretStoreインスタンス
    (Backend再起動を模擬)でも正しくdecryptできること。"""
    encrypted = encrypt("real-camera-password")
    assert encrypted is not None

    restarted_store = LocalSecretStore()
    assert restarted_store.decrypt(encrypted) == "real-camera-password"


def test_decrypt_via_module_helper_after_simulated_restart(monkeypatch):
    """app.services.secret_store.decrypt()自体も、再起動後の新しいstoreインスタンスに
    差し替えても同じ結果を返すこと(鍵が決定的に導出されているため)。"""
    encrypted = encrypt("another-password")

    import app.services.secret_store as secret_store_module

    monkeypatch.setattr(secret_store_module, "secret_store", LocalSecretStore())
    assert decrypt(encrypted) == "another-password"


def test_decrypt_returns_none_for_none_input():
    assert decrypt(None) is None


def test_encrypt_returns_none_for_falsy_input():
    assert encrypt(None) is None
    assert encrypt("") is None
