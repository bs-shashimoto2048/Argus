"""GET /api/system/process の基本的な形と、credentialを含まないことを確認する
(Issue #14: 複数Monitor稼働時のThread/Memory調査用診断endpoint)。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

import pytest

pytestmark = pytest.mark.unit


def test_process_diagnostics_returns_expected_shape():
    with TestClient(app) as client:
        response = client.get("/api/system/process")
    assert response.status_code == 200
    data = response.json()
    assert "pid" in data
    assert "python_thread_count" in data
    assert "active_monitor_runtimes" in data
    assert data["python_thread_count"] >= 1


def test_process_diagnostics_never_leaks_url_or_credentials():
    with TestClient(app) as client:
        response = client.get("/api/system/process")
    assert "http://" not in response.text
    assert "https://" not in response.text
    assert "password" not in response.text.lower()
