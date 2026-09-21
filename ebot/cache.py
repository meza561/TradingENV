import sqlite3
from pathlib import Path

SCHEMA = {
    "prices": """
        CREATE TABLE IF NOT EXISTS bars (
            symbol TEXT NOT NULL, date TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY (symbol, date)
        )""",
    "events": """
        CREATE TABLE IF NOT EXISTS events (
            ticker TEXT NOT NULL, cik TEXT NOT NULL,
            accession TEXT NOT NULL, accepted_at TEXT NOT NULL,
            PRIMARY KEY (accession)
        )""",
    "ciks": """
        CREATE TABLE IF NOT EXISTS ciks (
            ticker TEXT PRIMARY KEY, cik TEXT NOT NULL
        )""",
}


def get_conn(cache_dir: Path, name: str) -> sqlite3.Connection:
    if name not in SCHEMA:
        raise ValueError(f"unknown cache {name!r}; expected one of {sorted(SCHEMA)}")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cache_dir / f"{name}.db")
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA[name])
    conn.commit()
    return conn
