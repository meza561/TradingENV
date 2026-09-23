import os
import pytest
from pathlib import Path
from guard import claudebin


def fresh():
    claudebin.resolve.cache_clear()


def test_resolves_to_an_absolute_path():
    fresh()
    p = claudebin.resolve()
    assert Path(p).is_absolute() and Path(p).exists()


def test_argv_is_one_tool_only():
    fresh()
    a = claudebin.argv("some_tool")
    assert a[1:] == ["-p", "--allowedTools", "some_tool"]
    assert Path(a[0]).is_absolute(), "a bare 'claude' breaks under launchd"


def test_env_override_is_honoured(tmp_path, monkeypatch):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\n")
    fresh()
    monkeypatch.setenv("CLAUDE_BIN", str(fake))
    assert claudebin.resolve() == str(fake)
    fresh()


def test_bad_override_fails_loudly(monkeypatch):
    fresh()
    monkeypatch.setenv("CLAUDE_BIN", "/nope/claude")
    with pytest.raises(FileNotFoundError, match="does not exist"):
        claudebin.resolve()
    fresh()


def test_missing_everywhere_raises_actionable_error(monkeypatch):
    fresh()
    monkeypatch.delenv("CLAUDE_BIN", raising=False)
    monkeypatch.setattr(claudebin.shutil, "which", lambda n: None)
    monkeypatch.setattr(claudebin, "CANDIDATES", ())
    with pytest.raises(FileNotFoundError, match="Set CLAUDE_BIN"):
        claudebin.resolve()
    fresh()


def test_no_call_site_uses_a_bare_claude():
    """A bare 'claude' works in a shell and fails under the scheduler."""
    import guard
    root = Path(guard.__file__).parent
    offenders = []
    for f in root.glob("*.py"):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if '"claude"' in line and "claudebin" not in f.name:
                offenders.append(f"{f.name}:{i}")
    assert offenders == [], f"bare 'claude' in argv at {offenders}"
