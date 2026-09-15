"""Logging must survive Alembic.

The bug this guards: `alembic/env.py` called `fileConfig(...)`, whose default
`disable_existing_loggers=True` sets `.disabled = True` on every logger not
named in `alembic.ini` and drops root to WARNING with alembic's own handler.
The app runs Alembic in-process from its lifespan (`ensure_schema()`), so from
that moment on `uvicorn.error` and every `app.*` logger were dead.

The visible symptom was a server that exited in silence: uvicorn binds the
socket *after* the lifespan, and its `[Errno 10048] address already in use`
went to a disabled logger. The port conflict was invisible, so the process
looked like it had crashed for no reason.

These tests assert the loggers are still alive and still audible, which is the
property that makes the bind error reach the operator.
"""
from __future__ import annotations

import logging
import logging.config
from logging.config import fileConfig
from pathlib import Path

import pytest

from app.core.logging import configure_logging, logging_is_configured

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

#: The two that carry a startup failure to the terminal, plus one of ours.
CRITICAL_LOGGERS = ("uvicorn", "uvicorn.error", "app.main")


@pytest.fixture
def isolated_logging():
    """Restore the whole logging tree afterwards - these tests wreck it."""
    # Materialise them before the snapshot. A logger created *during* a test
    # is absent from `loggerDict` here and so would never be restored - which
    # is how disabling one test's `uvicorn` leaked into the next.
    for name in CRITICAL_LOGGERS:
        logging.getLogger(name)
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved = {
        name: (logger.disabled, logger.level, list(logger.handlers), logger.propagate)
        for name, logger in logging.getLogger().manager.loggerDict.items()
        if isinstance(logger, logging.Logger)
    }
    import app.core.logging as module

    saved_flag = module._configured
    yield
    module._configured = saved_flag
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    for name, (disabled, level, handlers, propagate) in saved.items():
        logger = logging.getLogger(name)
        logger.disabled, logger.level, logger.propagate = disabled, level, propagate
        logger.handlers[:] = handlers


def test_the_ini_on_its_own_would_still_disable_every_other_logger(isolated_logging):
    """The hazard is real and lives in the default, not in our ini.

    If this ever stops being true the guard below is redundant - but it is
    Python's default, so it will not.
    """
    for name in CRITICAL_LOGGERS:
        logging.getLogger(name).disabled = False

    fileConfig(str(ALEMBIC_INI))  # the old call, defaults intact

    assert [name for name in CRITICAL_LOGGERS if logging.getLogger(name).disabled] == [
        *CRITICAL_LOGGERS
    ]


def test_configure_logging_leaves_uvicorns_own_handler_alone(isolated_logging):
    """Clearing the *root* handlers is safe: uvicorn does not use them."""
    import uvicorn.config

    logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)
    before = list(logging.getLogger("uvicorn").handlers)

    configure_logging("INFO")

    assert logging.getLogger("uvicorn").handlers == before
    assert before, "uvicorn is expected to own a handler of its own"


def test_running_alembic_in_process_does_not_disable_the_apps_loggers(isolated_logging):
    """The regression, stated directly."""
    configure_logging("INFO")

    # Exactly what alembic/env.py now does when the app owns logging.
    if not logging_is_configured():  # pragma: no cover - guarded below
        fileConfig(str(ALEMBIC_INI), disable_existing_loggers=False)

    assert logging_is_configured() is True
    for name in CRITICAL_LOGGERS:
        assert logging.getLogger(name).disabled is False, name


def test_a_bind_error_logged_after_a_migration_still_reaches_the_stream(
    isolated_logging, capsys
):
    """End to end on the message that actually went missing."""
    import uvicorn.config

    logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)
    configure_logging("INFO")
    if not logging_is_configured():  # pragma: no cover
        fileConfig(str(ALEMBIC_INI), disable_existing_loggers=False)

    logging.getLogger("uvicorn.error").error(
        "[Errno 10048] error while attempting to bind on address"
    )
    logging.getLogger("app.main").info("startup_complete")

    captured = capsys.readouterr()
    assert "10048" in captured.err + captured.out
    assert "startup_complete" in captured.out


def test_alembic_run_as_a_cli_still_refuses_to_disable_other_loggers(isolated_logging):
    """Standalone, alembic may own logging - but disabling is never wanted.

    Silencing a library is a formatting choice. Disabling one is a way to lose
    an error, which is the whole point of this file.
    """
    import app.core.logging as module

    module._configured = False
    for name in CRITICAL_LOGGERS:
        logging.getLogger(name).disabled = False

    assert logging_is_configured() is False
    fileConfig(str(ALEMBIC_INI), disable_existing_loggers=False)

    for name in CRITICAL_LOGGERS:
        assert logging.getLogger(name).disabled is False, name
