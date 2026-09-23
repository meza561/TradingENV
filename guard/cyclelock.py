"""One cycle at a time. An entry cycle can take ~10 minutes against a
15-minute schedule, so overlapping runs are expected, not exceptional.
"""
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def cycle_lock(root: Path, name: str = ".guard.lock"):
    """Yields True if acquired, False if another cycle holds it.

    Uses O_EXCL create; a stale lock from a killed process is reclaimed when
    its recorded pid is gone, so a crash cannot wedge the scheduler forever.
    """
    p = Path(root) / name
    fd = None
    try:
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _stale(p):
                try:
                    p.unlink()
                    fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except (FileExistsError, FileNotFoundError):
                    yield False
                    return
            else:
                yield False
                return
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        fd = None
        yield True
    finally:
        if fd is not None:
            os.close(fd)
        try:
            if p.exists() and p.read_text().strip() == str(os.getpid()):
                p.unlink()
        except OSError:
            pass


def _stale(p: Path) -> bool:
    try:
        pid = int(p.read_text().strip())
    except (ValueError, OSError):
        return True                      # unreadable lock is stale
    if pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
        return False                     # alive
    except ProcessLookupError:
        return True
    except PermissionError:
        return False                     # exists, owned by someone else
