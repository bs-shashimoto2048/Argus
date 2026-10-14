"""ADMINログイン用の環境変数の値を生成する(Issue #34 Phase 2)。

使い方(リポジトリのルートで。Backendと同じPython環境で実行する):

    backend\\.venv\\Scripts\\python.exe scripts\\make_admin_password_hash.py

パスワードを対話入力(画面に表示しない)すると、次の2つを表示する。Backendを起動するユーザーの環境変数へ設定する(コマンド履歴に残さないこと)。

    ARGUS_ADMIN_PASSWORD_HASH  ... パスワードのPBKDF2-SHA256 hash(平文は保存しない)
    ARGUS_SESSION_SECRET       ... cookieの署名専用の乱数(ARGUS_SECRET_KEYとは別。再生成するとログイン中のADMINは無効になる)

どちらかが未設定だと管理者ログインは無効になり、全員が閲覧専用(VIEWER)になる。
"""
import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.auth import hash_password  # noqa: E402


def main() -> int:
    first = getpass.getpass("ADMINパスワード(12文字以上を推奨): ")
    if len(first) < 8:
        print("パスワードが短すぎます(8文字以上)。", file=sys.stderr)
        return 1
    if getpass.getpass("もう一度入力: ") != first:
        print("一致しません。", file=sys.stderr)
        return 1
    print()
    print(f"ARGUS_ADMIN_PASSWORD_HASH={hash_password(first)}")
    print(f"ARGUS_SESSION_SECRET={secrets.token_urlsafe(48)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
