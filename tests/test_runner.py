import datetime as dt
import json
import pytest
from pathlib import Path
from ebot.run_backtest import split_trades, write_report
from ebot.types import Trade


def mk(d):
    return Trade("X", dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc), d, d, d,
                 1.0, 1.1, 0.1, 0.05, 0.05)


def test_split_is_by_time_not_random():
    trades = [mk(dt.date(2020, 6, 1)), mk(dt.date(2021, 1, 1)),
              mk(dt.date(2022, 3, 1))]
    train, test = split_trades(trades, dt.date(2021, 1, 1))
    assert [t.entry_date for t in train] == [dt.date(2020, 6, 1)]
    assert len(test) == 2, "boundary date belongs to the TEST set"


def test_split_preserves_every_trade():
    trades = [mk(dt.date(2020, 6, 1)), mk(dt.date(2021, 1, 1))]
    train, test = split_trades(trades, dt.date(2021, 1, 1))
    assert len(train) + len(test) == len(trades)


def test_write_report_refuses_overwrite(tmp_path):
    p = tmp_path / "r.json"
    write_report(p, {"a": 1})
    with pytest.raises(FileExistsError, match="7.3"):
        write_report(p, {"a": 2})
    assert json.loads(p.read_text())["a"] == 1


def test_write_report_creates_parent_dir(tmp_path):
    p = tmp_path / "nested" / "deep" / "r.json"
    write_report(p, {"a": 1})
    assert p.exists()
