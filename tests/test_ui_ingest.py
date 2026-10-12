import os

from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite+pysqlite:////tmp/kanka-scribe-ui-test.db"
os.environ["SECRET_KEY"] = "test-secret-key-at-least-32-bytes!!"
os.environ["BOOTSTRAP_ADMIN_EMAIL"] = ""
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = ""

from kanka_scribe.auth_util import hash_password
from kanka_scribe.config import get_settings
from kanka_scribe.db import Base, get_engine, reset_engine
from kanka_scribe import db as dbmod
from kanka_scribe.main import create_app
from kanka_scribe.models import User, Workspace, WorkspaceMember


def _client() -> TestClient:
    get_settings.cache_clear()
    reset_engine()
    eng = get_engine()
    Base.metadata.drop_all(bind=eng)
    Base.metadata.create_all(bind=eng)
    assert dbmod.SessionLocal is not None
    db = dbmod.SessionLocal()
    user = User(
        email="admin@example.com",
        password_hash=hash_password("password12345"),
        is_admin=True,
    )
    db.add(user)
    db.flush()
    ws = Workspace(name="Home", handoff_dir="")
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="admin"))
    db.commit()
    db.close()
    return TestClient(create_app())


def test_ui_pages_and_upload():
    client = _client()
    login = client.post(
        "/ui/login",
        data={"email": "admin@example.com", "password": "password12345"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    for path in ("/ui/app", "/ui/jobs", "/ui/settings", "/ui/keys", "/ui/logs"):
        page = client.get(path)
        assert page.status_code == 200, path

    resp = client.post(
        "/ui/ingest",
        data={
            "workspace_id": "1",
            "title": "Test Session",
            "recap_markdown": "",
            "transcript": "",
            "run_sync": "",
        },
        files={"file": ("session.txt", b"**alice:**\nhello world\n", "text/plain")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/ui/jobs/")
    job_page = client.get(resp.headers["location"])
    assert job_page.status_code == 200
    assert b"Job #" in job_page.content


def test_api_key_create_and_auth():
    import re

    from kanka_scribe.api_keys import create_api_key
    from kanka_scribe import db as dbmod
    from kanka_scribe.models import User

    client = _client()
    assert dbmod.SessionLocal is not None
    db = dbmod.SessionLocal()
    user = db.query(User).filter_by(email="admin@example.com").one()
    _row, raw = create_api_key(db, user, "pipeline")
    db.close()

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"
    assert re.match(r"^ks_[0-9a-f]+_", raw)
