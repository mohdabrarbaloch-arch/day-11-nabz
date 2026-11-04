"""Shared pytest fixtures.

Each test module gets a fresh SQLite file so tests never see each other's
rows, and the app's dependency overrides point at that same engine.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-32ch")
os.environ.setdefault("BCRYPT_ROUNDS", "4")  # keep the suite fast
os.environ.setdefault("SEED_ON_STARTUP", "false")


@pytest.fixture()
def db_path() -> Iterator[str]:
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture()
def session(db_path: str) -> Iterator[Session]:
    from app.database import Base, get_session_factory, reset_engine

    reset_engine(f"sqlite:///{db_path}")
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=__import__("app.database", fromlist=["get_engine"]).get_engine())
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_path: str) -> Iterator[TestClient]:
    from app.database import Base, get_db, get_engine, reset_engine
    from app.main import app

    reset_engine(f"sqlite:///{db_path}")
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())

    def _override():
        from app.database import get_session_factory

        db = get_session_factory()()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={
            "email": "tester@nabz.pk",
            "full_name": "Test Clinician",
            "password": "strongpass123",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
