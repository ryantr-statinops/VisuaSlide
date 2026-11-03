"""Cross-process project lock for Windows and POSIX runtimes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from visuaslide.exceptions import LockUnavailableError


class ProjectLock:
    """Acquire an OS-managed one-byte lock released automatically on process exit."""

    def __init__(self, project_dir: str | Path) -> None:
        self.path = Path(project_dir).resolve() / "locks" / "refresh.lock"
        self._file: BinaryIO | None = None

    def acquire(self) -> ProjectLock:
        if self._file is not None:
            raise RuntimeError("this ProjectLock instance is already acquired")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            file = self.path.open("a+b")
            file.seek(0, os.SEEK_END)
            if file.tell() == 0:
                file.write(b"0")
                file.flush()
            file.seek(0)
            _lock_one_byte(file)
        except OSError as exc:
            if "file" in locals():
                file.close()
            raise LockUnavailableError(
                "Another process is already refreshing this project."
            ) from exc
        self._file = file
        return self

    def release(self) -> None:
        if self._file is None:
            return
        file = self._file
        self._file = None
        try:
            file.seek(0)
            _unlock_one_byte(file)
        finally:
            file.close()

    def __enter__(self) -> ProjectLock:
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


def _lock_one_byte(file: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_one_byte(file: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_UN)
