from ..core.security import secret_store

def encrypt(value: str | None) -> str | None:
    return secret_store.encrypt(value) if value else None
def decrypt(value: str | None) -> str | None:
    if not value: return None
    try: return secret_store.decrypt(value)
    except Exception: return None
