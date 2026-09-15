"""Shared fixtures.

The test database is a throwaway SQLite file in the OS temp directory. It is
pointed at via `AIS_DATABASE_URL` **before any app module is imported**, because
`app.db.session` builds its engine at import time from cached settings - so a
later override would be ignored and the tests would write to `runtime/db/ais.db`.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_TEST_DB = Path(tempfile.gettempdir()) / "ais_test.db"
_TEST_DB.unlink(missing_ok=True)

os.environ["AIS_ENVIRONMENT"] = "test"
os.environ["AIS_MLFLOW_ENABLED"] = "false"
os.environ["AIS_DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"

# Imported only after the environment is set.
from app.core.config import Settings, get_settings  # noqa: E402

# The suite must not read `backend/.env`.
#
# It used to, and that made the tests a function of whatever the developer had
# configured locally: putting a real OPENAI_API_KEY in `.env` broke every
# "no key configured" assertion, and setting AIS_WORKSPACE_BRANCHES broke every
# workspace test, because a setting outranks a training run by design. Neither
# was a defect in the code under test.
#
# Anything a test needs is set above or via monkeypatch, so the file is simply
# not read. This is done before the first `get_settings()` call, since the
# result is cached for the process.
Settings.model_config["env_file"] = None
get_settings.cache_clear()

from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
import app.models  # noqa: E402, F401 - registers every table


def test_database_is_isolated() -> None:
    """Guard: a misordered import would silently write to the real database."""
    assert "ais_test.db" in str(engine.url)


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    _TEST_DB.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    """Every test starts from an empty database, so seeded rows never leak
    between tests."""
    yield
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture(scope="session")
def app_instance():
    from app.main import create_app

    return create_app()


@pytest.fixture()
def client(app_instance) -> Iterator["TestClient"]:  # noqa: F821
    from fastapi.testclient import TestClient

    with TestClient(app_instance) as test_client:
        yield test_client
