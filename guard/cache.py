"""Small SQLite cache for chain structure. Separate from ebot's: different
project, different lifetime."""
import sqlite3
from pathlib import Path

SCHEMA = {
    "chaincache": """
        CREATE TABLE IF NOT EXISTS chaincache (
            day TEXT NOT NULL, k TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY (day, k)
        )""",
}


def get_conn(cache_dir: Path, name: str) -> sqlite3.Connection:
    if name not in SCHEMA:
        raise ValueError(f"unknown cache {name!r}")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cache_dir / f"{name}.db")
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA[name])
    conn.commit()
    return conn
