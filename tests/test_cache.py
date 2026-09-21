import sqlite3
import pytest
from ebot.cache import get_conn


def test_creates_schema_idempotently(tmp_path):
    c1 = get_conn(tmp_path, "prices")
    c1.execute("INSERT INTO bars VALUES ('AAPL','2026-01-02',1,2,0.5,1.5,100)")
    c1.commit()
    c1.close()
    c2 = get_conn(tmp_path, "prices")
    rows = c2.execute("SELECT * FROM bars").fetchall()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"


def test_events_table_rejects_duplicate_accession(tmp_path):
    c = get_conn(tmp_path, "events")
    c.execute("INSERT INTO events VALUES "
              "('AAPL','320193','0001-01','2026-01-02T16:05:00-05:00')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO events VALUES "
                  "('AAPL','320193','0001-01','2026-01-02T16:05:00-05:00')")


def test_bars_primary_key_is_symbol_date(tmp_path):
    c = get_conn(tmp_path, "prices")
    c.execute("INSERT INTO bars VALUES ('AAPL','2026-01-02',1,2,0.5,1.5,100)")
    c.execute("INSERT OR REPLACE INTO bars VALUES ('AAPL','2026-01-02',9,9,9,9,9)")
    rows = c.execute("SELECT * FROM bars").fetchall()
    assert len(rows) == 1, "same symbol+date must upsert, not duplicate"
    assert rows[0]["close"] == 9


def test_unknown_cache_name_rejected(tmp_path):
    with pytest.raises(ValueError):
        get_conn(tmp_path, "not_a_cache")
