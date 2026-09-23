"""Resolve the claude CLI.

launchd starts jobs with a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin), so a
bare "claude" in argv raises FileNotFoundError under the scheduler while
working fine in a shell. Resolving here fixes every call site at once and does
not depend on how the process was launched.
"""
import functools
import os
import shutil
from pathlib import Path

CANDIDATES = (
    Path.home() / ".local/bin/claude",
    Path("/opt/homebrew/bin/claude"),
    Path("/usr/local/bin/claude"),
)


@functools.lru_cache(maxsize=1)
def resolve() -> str:
    override = os.environ.get("CLAUDE_BIN")
    if override:
        if not Path(override).exists():
            raise FileNotFoundError(f"CLAUDE_BIN={override!r} does not exist")
        return override
    found = shutil.which("claude")
    if found:
        return found
    for c in CANDIDATES:
        if c.exists():
            return str(c)
    raise FileNotFoundError(
        "claude CLI not found on PATH or in the usual locations. "
        "Set CLAUDE_BIN to its absolute path.")


def argv(tool: str) -> list[str]:
    """Full argv for a one-tool headless call."""
    return [resolve(), "-p", "--allowedTools", tool]
