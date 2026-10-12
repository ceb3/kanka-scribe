import os

from fastapi.testclient import TestClient

# Configure before app/db engine is created.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:////tmp/kanka-scribe-test.db"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["BOOTSTRAP_ADMIN_EMAIL"] = ""
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = ""

from kanka_scribe.config import get_settings
from kanka_scribe.db import Base, get_engine, reset_engine
from kanka_scribe.main import create_app


def _fresh_client() -> TestClient:
    get_settings.cache_clear()
    reset_engine()
    eng = get_engine()
    Base.metadata.drop_all(bind=eng)
    Base.metadata.create_all(bind=eng)
    return TestClient(create_app())


def test_register_login_and_me():
    client = _fresh_client()
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "a@example.com", "password": "password123"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"
    assert me.json()["is_admin"] is True

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": "password123"},
    )
    assert login.status_code == 200
