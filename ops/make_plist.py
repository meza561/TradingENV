#!/usr/bin/env python3
"""Generate the launchd plist FROM the config, so cadence has one source
of truth. A cadence_minutes that launchd ignores is worse than no setting."""
import plistlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from guard.optconfig import load_option_config   # noqa: E402

REPO = Path(__file__).resolve().parent.parent
HOME = Path.home()
LABEL = "com.guard.options"


def build(cfg) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(REPO / ".venv/bin/python"), "-m", "guard.run_opt",
            "--config", str(REPO / "options.yaml"), "--root", str(REPO),
        ],
        "WorkingDirectory": str(REPO),
        "EnvironmentVariables": {
            "PATH": f"{HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:"
                    "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(HOME),
            "USER": HOME.name,
            "PYTHONUNBUFFERED": "1",
        },
        "StartInterval": cfg.cadence_minutes * 60,
        "StandardOutPath": str(REPO / "logs/options.out"),
        "StandardErrorPath": str(REPO / "logs/options.err"),
        "RunAtLoad": True,
    }


def main() -> int:
    cfg = load_option_config(REPO / "options.yaml")
    out = REPO / "ops/com.guard.options.local.plist"
    out.write_bytes(plistlib.dumps(build(cfg)))
    print(f"wrote {out.name}: every {cfg.cadence_minutes} min "
          f"({cfg.cadence_minutes * 60}s), {len(cfg.underlyings)} underlyings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
