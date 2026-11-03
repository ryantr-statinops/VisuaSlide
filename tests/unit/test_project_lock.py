import multiprocessing
from pathlib import Path

import pytest

from visuaslide.exceptions import LockUnavailableError
from visuaslide.locking import ProjectLock


def _hold_project_lock(project_dir: str, acquired, release) -> None:
    with ProjectLock(project_dir):
        acquired.put(True)
        release.wait(20)


def test_project_lock_is_released_when_holding_process_exits(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    acquired = context.Queue()
    release = context.Event()
    process = context.Process(
        target=_hold_project_lock,
        args=(str(tmp_path), acquired, release),
    )
    process.start()
    try:
        assert acquired.get(timeout=15) is True
        with pytest.raises(LockUnavailableError, match="already refreshing"):
            ProjectLock(tmp_path).acquire()
    finally:
        process.terminate()
        process.join(timeout=15)

    assert process.exitcode is not None
    with ProjectLock(tmp_path):
        pass


def test_project_locks_are_scoped_to_each_project(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    with ProjectLock(first):
        with ProjectLock(second):
            assert (first / "locks" / "refresh.lock").is_file()
            assert (second / "locks" / "refresh.lock").is_file()
