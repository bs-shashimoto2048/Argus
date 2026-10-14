import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# テストが実運用のSQLite(data/argus.db)を書き換えないよう、DB URLが明示されていない場合は
# テスト専用の一時DBを使う(app.core.configのimportより前に設定する必要がある)。
# 実運用Backend稼働中にpytestを実行すると、同じDBへMonitorのstatus等を書き込んでしまい、
# 有効Monitorのruntime(実カメラ)をテストプロセス側でも起動してしまっていた。
# CI等でARGUS_DATABASE_URLを明示した場合はそれを優先する。
if "ARGUS_DATABASE_URL" not in os.environ:
    _test_db_dir = Path(tempfile.mkdtemp(prefix="argus_pytest_"))
    os.environ["ARGUS_DATABASE_URL"] = f"sqlite:///{(_test_db_dir / 'argus_test.db').as_posix()}"


import pytest


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_db_schema():
    """一時DBへテーブルを作成する(lifespanを通さずDBへ直接アクセスするテストのため)。"""
    from app.core.database import Base, engine
    import app.models  # noqa: F401  モデルをmetadataへ登録する
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _admin_role_for_existing_tests(request):
    """既存のBackendテスト(書き込みAPIを認証なしで呼ぶ)は、ADMINとして扱う。認証そのもののテスト(pytestmark = real_auth)だけ、実際のcookie sessionを使う。
    本番コードに「認証を切る」スイッチは無く、テストのdependency_overridesだけで切り替える。"""
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    from app.core import auth
    from app.main import app
    app.dependency_overrides[auth.current_role] = lambda: auth.ADMIN
    yield
    app.dependency_overrides.pop(auth.current_role, None)
