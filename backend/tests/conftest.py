from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEST_DATABASE = Path(tempfile.gettempdir()) / f"paix-pytest-{os.getpid()}.db"
os.environ["PAIX_DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DATABASE.as_posix()}"
os.environ["PAIX_LOG_LEVEL"] = "WARNING"
os.environ.setdefault("RUN_LIVE_API_TESTS", "0")
os.environ["PAIX_TTS_PROVIDER"] = "mock"


def pytest_sessionfinish() -> None:
    for suffix in ("", "-shm", "-wal"):
        try:
            TEST_DATABASE.with_name(TEST_DATABASE.name + suffix).unlink(missing_ok=True)
        except OSError:
            pass
