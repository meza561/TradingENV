import os
from pathlib import Path
from guard.cyclelock import cycle_lock


def test_acquires_and_releases(tmp_path):
    with cycle_lock(tmp_path) as got:
        assert got is True
        assert (tmp_path / ".guard.lock").exists()
    assert not (tmp_path / ".guard.lock").exists()


def test_second_holder_is_refused(tmp_path):
    with cycle_lock(tmp_path) as a:
        assert a is True
        with cycle_lock(tmp_path) as b:
            assert b is False, "overlapping cycles must not both run"


def test_stale_lock_from_dead_pid_is_reclaimed(tmp_path):
    (tmp_path / ".guard.lock").write_text("999999")    # pid that cannot exist
    with cycle_lock(tmp_path) as got:
        assert got is True, "a crashed cycle must not wedge the scheduler"


def test_unreadable_lock_is_reclaimed(tmp_path):
    (tmp_path / ".guard.lock").write_text("not-a-pid")
    with cycle_lock(tmp_path) as got:
        assert got is True


def test_lock_released_even_when_body_raises(tmp_path):
    try:
        with cycle_lock(tmp_path) as got:
            assert got
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert not (tmp_path / ".guard.lock").exists()


def test_live_pid_is_not_reclaimed(tmp_path):
    (tmp_path / ".guard.lock").write_text(str(os.getpid() if False else 1))
    with cycle_lock(tmp_path) as got:
        assert got is False, "pid 1 is alive; the lock must be respected"
