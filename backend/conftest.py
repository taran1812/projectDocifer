"""Root conftest for the Docifer backend test suite.

On Windows the system temp directory may be permission-locked (e.g. after a
previous pytest run under a different privilege level).  When that happens the
built-in ``tmp_path`` fixture raises PermissionError before any test code runs.

This conftest patches the ``TempPathFactory`` base-temp directory to fall back
to a local ``.pytest_tmp`` directory inside the project when the system temp is
not accessible.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


def _local_basetemp() -> Path:
    """Return a writable basetemp dir inside the project tree."""
    here = Path(__file__).parent
    basetemp = here / ".pytest_tmp"
    basetemp.mkdir(exist_ok=True)
    return basetemp


def pytest_configure(config: pytest.Config) -> None:
    """Redirect tmp_path to a local dir if the system temp is inaccessible."""
    os.environ.setdefault("DATABASE_URL", "sqlite+psycopg2:///:memory:")
    system_temp = Path(tempfile.gettempdir())
    sentinel = system_temp / f"pytest-of-{os.environ.get('USERNAME', os.environ.get('USER', 'user'))}"
    if sentinel.exists():
        try:
            list(sentinel.iterdir())
        except PermissionError:
            # System temp is locked — redirect to local dir.
            config.option.basetemp = str(_local_basetemp())
    # If sentinel doesn't exist yet, tmp_path will create it normally (no issue).
