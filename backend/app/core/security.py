from abc import ABC, abstractmethod
import base64
import hashlib
import os

class SecretStore(ABC):
    @abstractmethod
    def encrypt(self, value: str) -> str: ...
    @abstractmethod
    def decrypt(self, value: str) -> str: ...

class LocalSecretStore(SecretStore):
    """PoC用。ARGUS_SECRET_KEYが同じ実行ユーザー環境で必要です。"""
    def __init__(self) -> None:
        from cryptography.fernet import Fernet
        raw = os.getenv("ARGUS_SECRET_KEY")
        key = raw.encode() if raw else base64.urlsafe_b64encode(hashlib.sha256(b"argus-dev-key-change-me").digest())
        self._fernet = Fernet(key)
    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()
    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode()).decode()

secret_store = LocalSecretStore()
