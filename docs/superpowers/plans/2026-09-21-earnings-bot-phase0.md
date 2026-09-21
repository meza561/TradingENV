# Earnings Bot — Phase 0 (Data Layer & Backtest) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an honest, look-ahead-free backtest of the pre-registered earnings-reaction signal, and report whether it clears the success bar.

**Architecture:** Three layers, each independently testable. `edgar.py` pulls historical 8-K Item 2.02 acceptance timestamps directly from SEC's public API (no auth). `prices.py` pulls daily OHLCV once via a headless Claude call with a read-only tool allowlist, caching to SQLite. `backtest.py` is pure functions over those two caches — no network, fully deterministic, trivially testable.

**Tech Stack:** Python 3.14, stdlib-first (`urllib`, `sqlite3`, `statistics`, `datetime`). External deps limited to `pydantic` (config validation, per spec §9), `pyyaml`, and `pytest`. No numpy, no pandas, no data vendor SDK.

**Spec:** `docs/superpowers/specs/2026-09-21-earnings-bot-design.md`

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include these.

- **No order-placing tool may be invoked at any point in Phase 0.** Not in code, not in tests, not manually. Phase 0 is read-only by construction.
- The price fetcher's `--allowedTools` allowlist contains **only** `mcp__robinhood-trading__get_equity_historicals`. No other tool.
- **The signal definition (spec §6) is pre-registered and MUST NOT be altered** during implementation. If a gate condition seems wrong while coding, stop and raise it — do not silently adjust it.
- **The backtest runs ONCE against the test set** (spec §7.3). No parameter is adjusted and re-run to improve results.
- Out-of-sample split is by **time**, never randomly: train `< 2021-01-01`, test `>= 2021-01-01`.
- Success criteria, all three required (spec §7.4): mean excess vs SPY with **t-statistic >= 2.0**; **hit rate > 50%**; **max drawdown <= 25%**.
- Whitelist, fixed: `AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, JPM, WMT, COST, HD, NFLX`
- Price history floor: **2014-01-02** (verified available depth).
- SEC requires a declared User-Agent; requests rate-limited to **10/sec**.
- **R10: no credential is ever stored, printed, or logged.** Phase 0 touches no credential — the headless call reuses Claude Code's own auth.
- All timestamps internally are **timezone-aware**. Event times are converted to **US/Eastern** before any session logic.

## File Structure

```
ebot/
  __init__.py
  types.py        Bar, Event, Trade frozen dataclasses. Shared vocabulary.
  config.py       Pydantic Config model + load_config(). Fails loud on bad input.
  cache.py        SQLite connection helper + schema creation. One job.
  edgar.py        SEC public API: ticker->CIK, 8-K Item 2.02 -> Event list.
  prices.py       Headless-Claude OHLCV fetch -> Bar list, cached.
  calendar.py     Session calendar + entry-timing rule (spec 6.1).
  gate.py         Gate conditions G1-G5 (spec 6.2). Pure functions.
  backtest.py     Event -> Trade. Entry/exit/excess return.
  stats.py        t-stat, hit rate, max drawdown, criteria evaluation.
  run_backtest.py Entry point. Train/test split, run-once, emit report.
tests/
  test_config.py test_edgar.py test_prices.py test_calendar.py
  test_gate.py test_backtest.py test_stats.py test_integrity.py
config.example.yaml
pyproject.toml
```

Split by responsibility. `calendar.py` and `gate.py` are separate because the entry-timing rule and the gate conditions fail differently and are reviewed differently — the timing rule is where an off-by-one silently corrupts every result, so it gets its own exhaustive test file.

---

### Task 1: Project scaffolding, shared types, and config

**Files:**
- Create: `pyproject.toml`, `ebot/__init__.py`, `ebot/types.py`, `ebot/config.py`, `config.example.yaml`, `tests/__init__.py` (empty — required so Task 8 can `from tests.test_gate import with_event`)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `Bar`, `Event`, `Trade` frozen dataclasses; `Config` pydantic model; `load_config(path: Path) -> Config`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest, datetime as dt
from pathlib import Path
from ebot.config import load_config, Config
from ebot.types import Bar, Event, Trade

def test_loads_example_config():
    cfg = load_config(Path("config.example.yaml"))
    assert isinstance(cfg, Config)
    assert "AAPL" in cfg.whitelist
    assert len(cfg.whitelist) == 12
    assert cfg.train_test_split == dt.date(2021, 1, 1)
    assert cfg.price_floor == dt.date(2014, 1, 2)

def test_rejects_unknown_field(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("whitelist: [AAPL]\nbogus_field: 1\n")
    with pytest.raises(Exception):
        load_config(p)

def test_rejects_empty_whitelist(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("whitelist: []\n")
    with pytest.raises(Exception):
        load_config(p)

def test_bar_is_frozen():
    b = Bar(symbol="AAPL", date=dt.date(2026, 1, 2), open=1.0, high=2.0,
            low=0.5, close=1.5, volume=100)
    with pytest.raises(Exception):
        b.close = 99.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebot'`

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[project]
name = "ebot"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["pydantic>=2.0", "pyyaml>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.setuptools.packages.find]
include = ["ebot*"]
```

```python
# ebot/types.py
from dataclasses import dataclass
import datetime as dt

@dataclass(frozen=True)
class Bar:
    symbol: str
    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int

@dataclass(frozen=True)
class Event:
    """An 8-K Item 2.02 filing. accepted_at is tz-aware US/Eastern."""
    ticker: str
    cik: str
    accession: str
    accepted_at: dt.datetime

@dataclass(frozen=True)
class Trade:
    ticker: str
    accepted_at: dt.datetime
    t0: dt.date
    entry_date: dt.date
    exit_date: dt.date
    entry_px: float
    exit_px: float
    ret: float
    spy_ret: float
    excess: float
```

```python
# ebot/config.py
from pathlib import Path
import datetime as dt
import yaml
from pydantic import BaseModel, Field, field_validator

class Config(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    whitelist: list[str] = Field(min_length=1)
    benchmark: str = "SPY"
    price_floor: dt.date = dt.date(2014, 1, 2)
    train_test_split: dt.date = dt.date(2021, 1, 1)
    hold_days: int = 3
    gap_min_pct: float = 2.0
    volume_mult: float = 1.5
    min_dollar_volume: float = 50_000_000.0
    extended_mult: float = 1.15
    lookback_sessions: int = 20
    sma_window: int = 50
    sec_user_agent: str
    cache_dir: Path = Path("cache")

    @field_validator("whitelist")
    @classmethod
    def upper_unique(cls, v: list[str]) -> list[str]:
        out = [s.strip().upper() for s in v]
        if len(set(out)) != len(out):
            raise ValueError("whitelist contains duplicates")
        return out

def load_config(path: Path = Path("config.yaml")) -> Config:
    data = yaml.safe_load(path.read_text()) or {}
    return Config(**data)
```

```yaml
# config.example.yaml
whitelist: [AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, JPM, WMT, COST, HD, NFLX]
benchmark: SPY
price_floor: 2014-01-02
train_test_split: 2021-01-01
hold_days: 3
gap_min_pct: 2.0
volume_mult: 1.5
min_dollar_volume: 50000000.0
extended_mult: 1.15
lookback_sessions: 20
sma_window: 50
sec_user_agent: "ebot-research contact@example.com"
cache_dir: cache
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
touch tests/__init__.py
git add pyproject.toml ebot/ tests/__init__.py tests/test_config.py config.example.yaml
git commit -m "feat: project scaffolding, shared types, validated config"
```

---

### Task 2: SQLite cache layer

**Files:**
- Create: `ebot/cache.py`
- Test: `tests/test_cache.py`

**Interfaces:**
- Consumes: `Config.cache_dir`
- Produces: `get_conn(cache_dir: Path, name: str) -> sqlite3.Connection` — returns a connection with schema already created and `row_factory = sqlite3.Row`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cache.py
from ebot.cache import get_conn

def test_creates_schema_idempotently(tmp_path):
    c1 = get_conn(tmp_path, "prices")
    c1.execute("INSERT INTO bars VALUES ('AAPL','2026-01-02',1,2,0.5,1.5,100)")
    c1.commit(); c1.close()
    c2 = get_conn(tmp_path, "prices")   # second call must not wipe or error
    rows = c2.execute("SELECT * FROM bars").fetchall()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"

def test_events_table_rejects_duplicate_accession(tmp_path):
    import sqlite3, pytest
    c = get_conn(tmp_path, "events")
    c.execute("INSERT INTO events VALUES ('AAPL','320193','0001-01','2026-01-02T16:05:00-05:00')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO events VALUES ('AAPL','320193','0001-01','2026-01-02T16:05:00-05:00')")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebot.cache'`

- [ ] **Step 3: Write minimal implementation**

```python
# ebot/cache.py
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
    cache_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cache_dir / f"{name}.db")
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA[name])
    conn.commit()
    return conn
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cache.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add ebot/cache.py tests/test_cache.py
git commit -m "feat: sqlite cache layer with idempotent schema"
```

---

### Task 3: EDGAR — ticker to CIK resolution

**Files:**
- Create: `ebot/edgar.py`
- Test: `tests/test_edgar.py`

**Interfaces:**
- Consumes: `get_conn` (Task 2), `Config.sec_user_agent`
- Produces: `resolve_cik(ticker: str, cfg: Config, fetch=None) -> str` returning a 10-digit zero-padded CIK. `fetch` is an injectable callable `(url: str, ua: str) -> bytes` for testing.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_edgar.py
import json, pytest
from ebot.edgar import resolve_cik
from ebot.config import load_config
from pathlib import Path

FAKE_TICKERS = json.dumps({
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
}).encode()

def cfg_for(tmp_path):
    c = load_config(Path("config.example.yaml"))
    return c.model_copy(update={"cache_dir": tmp_path})

def test_resolves_and_zero_pads(tmp_path):
    calls = []
    def fake(url, ua):
        calls.append(url); return FAKE_TICKERS
    assert resolve_cik("AAPL", cfg_for(tmp_path), fetch=fake) == "0000320193"
    assert len(calls) == 1

def test_second_call_uses_cache(tmp_path):
    calls = []
    def fake(url, ua):
        calls.append(url); return FAKE_TICKERS
    c = cfg_for(tmp_path)
    resolve_cik("AAPL", c, fetch=fake)
    resolve_cik("AAPL", c, fetch=fake)
    assert len(calls) == 1, "second resolve must hit cache, not network"

def test_unknown_ticker_raises(tmp_path):
    def fake(url, ua): return FAKE_TICKERS
    with pytest.raises(KeyError):
        resolve_cik("NOSUCH", cfg_for(tmp_path), fetch=fake)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_edgar.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebot.edgar'`

- [ ] **Step 3: Write minimal implementation**

```python
# ebot/edgar.py
import json, time, urllib.request
from ebot.cache import get_conn
from ebot.config import Config

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_last_call = [0.0]

def _fetch(url: str, ua: str) -> bytes:
    """Rate-limited to 10/sec per SEC policy."""
    elapsed = time.monotonic() - _last_call[0]
    if elapsed < 0.1:
        time.sleep(0.1 - elapsed)
    _last_call[0] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": ua,
                                               "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

def resolve_cik(ticker: str, cfg: Config, fetch=None) -> str:
    fetch = fetch or _fetch
    ticker = ticker.strip().upper()
    conn = get_conn(cfg.cache_dir, "ciks")
    row = conn.execute("SELECT cik FROM ciks WHERE ticker = ?", (ticker,)).fetchone()
    if row:
        return row["cik"]
    raw = json.loads(fetch(TICKERS_URL, cfg.sec_user_agent))
    mapping = {e["ticker"].upper(): f"{int(e['cik_str']):010d}" for e in raw.values()}
    conn.executemany("INSERT OR REPLACE INTO ciks VALUES (?, ?)", mapping.items())
    conn.commit()
    if ticker not in mapping:
        raise KeyError(f"ticker not found in SEC registry: {ticker}")
    return mapping[ticker]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_edgar.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add ebot/edgar.py tests/test_edgar.py
git commit -m "feat: EDGAR ticker-to-CIK resolution with cache and rate limit"
```

---

### Task 4: EDGAR — 8-K Item 2.02 event extraction

**Files:**
- Modify: `ebot/edgar.py`
- Test: `tests/test_edgar.py`

**Interfaces:**
- Consumes: `resolve_cik` (Task 3), `Event` (Task 1)
- Produces: `fetch_events(ticker: str, cfg: Config, fetch=None) -> list[Event]` — returns events sorted ascending by `accepted_at`, tz-aware US/Eastern, deduplicated by accession, filtered to `>= cfg.price_floor`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_edgar.py
import datetime as dt
from zoneinfo import ZoneInfo
from ebot.edgar import fetch_events

SUBS = json.dumps({"filings": {"recent": {
    "accessionNumber": ["0001-24-01", "0001-24-02", "0001-24-03", "0001-13-99"],
    "form":            ["8-K",       "8-K",       "10-Q",      "8-K"],
    "items":           ["2.02,7.01", "5.02",      "",          "2.02"],
    "acceptanceDateTime": ["2024-05-02T16:30:12.000Z", "2024-06-01T09:00:00.000Z",
                           "2024-05-02T16:30:12.000Z", "2013-01-01T16:30:00.000Z"],
}}}).encode()

def test_keeps_only_8k_item_202(tmp_path):
    def fake(url, ua):
        return FAKE_TICKERS if "company_tickers" in url else SUBS
    evs = fetch_events("AAPL", cfg_for(tmp_path), fetch=fake)
    assert [e.accession for e in evs] == ["0001-24-01"]

def test_drops_events_before_price_floor(tmp_path):
    def fake(url, ua):
        return FAKE_TICKERS if "company_tickers" in url else SUBS
    evs = fetch_events("AAPL", cfg_for(tmp_path), fetch=fake)
    assert all(e.accepted_at.date() >= dt.date(2014, 1, 2) for e in evs)

def test_converts_to_eastern(tmp_path):
    def fake(url, ua):
        return FAKE_TICKERS if "company_tickers" in url else SUBS
    e = fetch_events("AAPL", cfg_for(tmp_path), fake)[0]
    assert e.accepted_at.tzinfo is not None
    # 16:30:12Z on 2024-05-02 is 12:30:12 EDT
    assert e.accepted_at.astimezone(ZoneInfo("US/Eastern")).hour == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_edgar.py -k events -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_events'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to ebot/edgar.py
import datetime as dt
from zoneinfo import ZoneInfo
from ebot.types import Event

ET = ZoneInfo("US/Eastern")
SUBS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

def fetch_events(ticker: str, cfg: Config, fetch=None) -> list[Event]:
    fetch = fetch or _fetch
    ticker = ticker.strip().upper()
    cik = resolve_cik(ticker, cfg, fetch)
    raw = json.loads(fetch(SUBS_URL.format(cik=cik), cfg.sec_user_agent))
    recent = raw["filings"]["recent"]
    out: dict[str, Event] = {}
    for acc, form, items, accepted in zip(
        recent["accessionNumber"], recent["form"],
        recent["items"], recent["acceptanceDateTime"],
    ):
        if form != "8-K":
            continue
        if "2.02" not in [i.strip() for i in (items or "").split(",")]:
            continue
        ts = dt.datetime.fromisoformat(accepted.replace("Z", "+00:00")).astimezone(ET)
        if ts.date() < cfg.price_floor:
            continue
        out[acc] = Event(ticker=ticker, cik=cik, accession=acc, accepted_at=ts)
    return sorted(out.values(), key=lambda e: e.accepted_at)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_edgar.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add ebot/edgar.py tests/test_edgar.py
git commit -m "feat: extract 8-K Item 2.02 events with ET acceptance timestamps"
```

---

### Task 5: Price fetch via headless Claude, chunked by year

**Files:**
- Create: `ebot/prices.py`
- Test: `tests/test_prices.py`

**Interfaces:**
- Consumes: `Bar` (Task 1), `get_conn` (Task 2)
- Produces: `load_bars(symbol, cfg) -> list[Bar]`; `fetch_year(symbol, year, cfg, runner=None) -> list[Bar]`; `fetch_all_years(symbol, cfg, runner=None) -> list[Bar]`; `ALLOWED_TOOLS`

**Why chunked:** a single full-history request returns roughly 555 KB of JSON for
one symbol — observed in practice, and large enough to exceed the tool-result
limit. One call per calendar year keeps each response near 45 KB. Year chunks
are also individually cacheable, so an interrupted fetch resumes instead of
restarting.

**CRITICAL:** the allowlist contains exactly one read-only tool. A test asserts
no order tool can appear in the argv.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prices.py
import json, datetime as dt
from pathlib import Path
from ebot.prices import fetch_year, fetch_all_years, load_bars, ALLOWED_TOOLS
from ebot.config import load_config

def cfg_for(tmp_path):
    return load_config(Path("config.example.yaml")).model_copy(
        update={"cache_dir": tmp_path})

def payload(year):
    return json.dumps({"bars": [
        {"date": f"{year}-01-02", "open": 1.0, "high": 2.0, "low": 0.5,
         "close": 1.5, "volume": 100},
        {"date": f"{year}-01-03", "open": 1.5, "high": 2.5, "low": 1.0,
         "close": 2.0, "volume": 200},
    ]})

def test_allowlist_is_read_only():
    assert ALLOWED_TOOLS == ["mcp__robinhood-trading__get_equity_historicals"]
    joined = " ".join(ALLOWED_TOOLS).lower()
    for banned in ("place_", "cancel_", "order", "exercise"):
        assert banned not in joined, f"forbidden tool family {banned!r} in allowlist"

def test_argv_never_contains_order_tool(tmp_path):
    seen = {}
    def runner(argv):
        seen["argv"] = argv; return payload(2020)
    fetch_year("AAPL", 2020, cfg_for(tmp_path), runner=runner)
    flat = " ".join(seen["argv"])
    assert "place_equity_order" not in flat
    assert "--allowedTools" in flat

def test_request_window_is_bounded_to_the_year(tmp_path):
    seen = {}
    def runner(argv):
        seen["argv"] = argv; return payload(2020)
    fetch_year("AAPL", 2020, cfg_for(tmp_path), runner=runner)
    flat = " ".join(seen["argv"])
    assert "2020-01-01" in flat and "2020-12-31" in flat

def test_fetch_all_years_skips_cached_years(tmp_path):
    calls = []
    def runner(argv):
        calls.append(argv)
        year = next(a for a in argv if "-01-01" in a)[:4]
        return payload(year)
    c = cfg_for(tmp_path).model_copy(update={"price_floor": dt.date(2020, 1, 1)})
    fetch_all_years("AAPL", c, runner=runner)
    n_first = len(calls)
    assert n_first >= 2
    fetch_all_years("AAPL", c, runner=runner)   # second pass: all cached
    assert len(calls) == n_first, "cached years must not be refetched"

def test_rejects_unparseable_output(tmp_path):
    import pytest
    def runner(argv): return "I could not find that data, sorry!"
    with pytest.raises(ValueError):
        fetch_year("AAPL", 2020, cfg_for(tmp_path), runner=runner)

def test_rejects_bars_outside_requested_year(tmp_path):
    import pytest
    def runner(argv):
        return json.dumps({"bars": [
            {"date": "2019-06-01", "open": 1, "high": 1, "low": 1,
             "close": 1, "volume": 1}]})
    with pytest.raises(ValueError, match="outside requested year"):
        fetch_year("AAPL", 2020, cfg_for(tmp_path), runner=runner)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prices.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebot.prices'`

- [ ] **Step 3: Write minimal implementation**

```python
# ebot/prices.py
import json, re, subprocess, datetime as dt
from ebot.cache import get_conn
from ebot.config import Config
from ebot.types import Bar

ALLOWED_TOOLS = ["mcp__robinhood-trading__get_equity_historicals"]

PROMPT = """Call get_equity_historicals for symbol {symbol} with
start_time="{start}T00:00:00Z", end_time="{end}T23:59:59Z", interval="day",
adjustment_type="split", bounds="regular".
Reply with ONLY a JSON object, no prose, no code fence:
{{"bars":[{{"date":"YYYY-MM-DD","open":0,"high":0,"low":0,"close":0,"volume":0}}]}}"""

def _run(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=300, check=True).stdout

def _cached_years(symbol: str, cfg: Config) -> set[int]:
    conn = get_conn(cfg.cache_dir, "prices")
    rows = conn.execute(
        "SELECT DISTINCT substr(date,1,4) AS y FROM bars WHERE symbol = ?",
        (symbol,)).fetchall()
    return {int(r["y"]) for r in rows}

def fetch_year(symbol: str, year: int, cfg: Config, runner=None) -> list[Bar]:
    runner = runner or _run
    start, end = f"{year}-01-01", f"{year}-12-31"
    argv = ["claude", "-p", "--allowedTools", ",".join(ALLOWED_TOOLS),
            PROMPT.format(symbol=symbol, start=start, end=end)]
    assert not any("place_" in a or "cancel_" in a for a in argv), \
        "order tool leaked into price fetch argv"
    out = runner(argv)
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        raise ValueError(f"no JSON in claude output for {symbol} {year}: {out[:200]!r}")
    try:
        rows = json.loads(m.group(0))["bars"]
    except (json.JSONDecodeError, KeyError) as e:
        raise ValueError(f"unparseable bars for {symbol} {year}: {e}") from e

    bars = []
    for r in rows:
        d = dt.date.fromisoformat(r["date"])
        if d.year != year:
            raise ValueError(
                f"{symbol}: bar {d} outside requested year {year}")
        bars.append(Bar(symbol=symbol, date=d, open=float(r["open"]),
                        high=float(r["high"]), low=float(r["low"]),
                        close=float(r["close"]), volume=int(r["volume"])))
    conn = get_conn(cfg.cache_dir, "prices")
    conn.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?)",
                     [(b.symbol, b.date.isoformat(), b.open, b.high, b.low,
                       b.close, b.volume) for b in bars])
    conn.commit()
    return sorted(bars, key=lambda b: b.date)

def fetch_all_years(symbol: str, cfg: Config, runner=None) -> list[Bar]:
    have = _cached_years(symbol, cfg)
    this_year = dt.date.today().year
    for year in range(cfg.price_floor.year, this_year + 1):
        if year in have and year != this_year:
            continue                      # current year always refetched
        fetch_year(symbol, year, cfg, runner)
    return load_bars(symbol, cfg)

def load_bars(symbol: str, cfg: Config) -> list[Bar]:
    conn = get_conn(cfg.cache_dir, "prices")
    rows = conn.execute(
        "SELECT * FROM bars WHERE symbol = ? ORDER BY date", (symbol,)).fetchall()
    return [Bar(symbol=r["symbol"], date=dt.date.fromisoformat(r["date"]),
                open=r["open"], high=r["high"], low=r["low"],
                close=r["close"], volume=r["volume"]) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prices.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add ebot/prices.py tests/test_prices.py
git commit -m "feat: year-chunked price fetch with read-only tool allowlist"
```

---

### Task 5b: Bar data-integrity validation

**Files:**
- Create: `ebot/validate_bars.py`
- Test: `tests/test_validate_bars.py`

**Interfaces:**
- Consumes: `Bar` (Task 1), `Config` (Task 1)
- Produces: `BarIssue` frozen dataclass (`symbol, date, kind, detail`);
  `validate_bars(bars: list[Bar], cfg: Config) -> list[BarIssue]`;
  `FATAL_KINDS: frozenset[str]`

**Severity model.** Structural impossibilities are fatal — an OHLC violation or a
duplicate date means the data is wrong, and a backtest on wrong data is worse
than no backtest. Statistical oddities are warnings: a 30% single-day move is
usually a real event (META fell 26% on 2022-02-03), so flagging is right and
failing is not.

| kind | Meaning | Fatal |
|------|---------|-------|
| `ohlc` | `high < low`, price outside `[low, high]`, non-positive price, negative volume | yes |
| `duplicate` | same symbol+date twice | yes |
| `count` | calendar year with < 220 or > 260 sessions | no |
| `gap` | > 5 consecutive missing business days | no |
| `extreme` | abs(close-to-close return) > 25% | no |

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validate_bars.py
import datetime as dt
from pathlib import Path
from ebot.config import load_config
from ebot.types import Bar
from ebot.validate_bars import validate_bars, FATAL_KINDS

CFG = load_config(Path("config.example.yaml"))

def good_year(year=2020, n=252, px=100.0):
    out, d = [], dt.date(year, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(Bar("X", d, px, px * 1.01, px * 0.99, px, 1_000_000))
        d += dt.timedelta(days=1)
    return out

def kinds(issues):
    return {i.kind for i in issues}

def test_clean_data_has_no_issues():
    assert validate_bars(good_year(), CFG) == []

def test_high_below_low_is_fatal():
    bars = good_year()
    bars[10] = Bar("X", bars[10].date, 100, 90.0, 110.0, 100, 1_000_000)
    issues = validate_bars(bars, CFG)
    assert "ohlc" in kinds(issues)
    assert "ohlc" in FATAL_KINDS

def test_close_outside_high_low_is_fatal():
    bars = good_year()
    bars[10] = Bar("X", bars[10].date, 100, 101.0, 99.0, 500.0, 1_000_000)
    assert "ohlc" in kinds(validate_bars(bars, CFG))

def test_zero_price_is_fatal():
    bars = good_year()
    bars[10] = Bar("X", bars[10].date, 0.0, 0.0, 0.0, 0.0, 1_000_000)
    assert "ohlc" in kinds(validate_bars(bars, CFG))

def test_negative_volume_is_fatal():
    bars = good_year()
    b = bars[10]
    bars[10] = Bar("X", b.date, b.open, b.high, b.low, b.close, -5)
    assert "ohlc" in kinds(validate_bars(bars, CFG))

def test_duplicate_date_is_fatal():
    bars = good_year()
    bars.append(bars[10])
    issues = validate_bars(bars, CFG)
    assert "duplicate" in kinds(issues)
    assert "duplicate" in FATAL_KINDS

def test_short_year_flagged_as_count():
    issues = validate_bars(good_year(n=150), CFG)
    assert "count" in kinds(issues)
    assert "count" not in FATAL_KINDS

def test_long_gap_flagged():
    bars = good_year()
    del bars[100:115]                      # ~3 weeks missing
    assert "gap" in kinds(validate_bars(bars, CFG))

def test_extreme_move_flagged_not_fatal():
    bars = good_year()
    b = bars[50]
    bars[50] = Bar("X", b.date, 100, 200.0, 99.0, 180.0, 1_000_000)
    issues = validate_bars(bars, CFG)
    assert "extreme" in kinds(issues)
    assert "extreme" not in FATAL_KINDS

def test_issue_carries_symbol_and_date():
    bars = good_year()
    bars[10] = Bar("X", bars[10].date, 100, 90.0, 110.0, 100, 1_000_000)
    i = next(i for i in validate_bars(bars, CFG) if i.kind == "ohlc")
    assert i.symbol == "X" and i.date == bars[10].date and i.detail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validate_bars.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebot.validate_bars'`

- [ ] **Step 3: Write minimal implementation**

```python
# ebot/validate_bars.py
import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass
from ebot.config import Config
from ebot.types import Bar

FATAL_KINDS = frozenset({"ohlc", "duplicate"})
MAX_GAP_BUSINESS_DAYS = 5
EXTREME_MOVE = 0.25
MIN_SESSIONS, MAX_SESSIONS = 220, 260

@dataclass(frozen=True)
class BarIssue:
    symbol: str
    date: dt.date | None
    kind: str
    detail: str

def _business_days(a: dt.date, b: dt.date) -> int:
    n, d = 0, a + dt.timedelta(days=1)
    while d < b:
        if d.weekday() < 5:
            n += 1
        d += dt.timedelta(days=1)
    return n

def validate_bars(bars: list[Bar], cfg: Config) -> list[BarIssue]:
    issues: list[BarIssue] = []
    if not bars:
        return issues
    sym = bars[0].symbol

    for b in bars:
        bad = (b.high < b.low
               or not (b.low <= b.open <= b.high)
               or not (b.low <= b.close <= b.high)
               or min(b.open, b.high, b.low, b.close) <= 0
               or b.volume < 0)
        if bad:
            issues.append(BarIssue(sym, b.date, "ohlc",
                f"o={b.open} h={b.high} l={b.low} c={b.close} v={b.volume}"))

    for d, n in Counter(b.date for b in bars).items():
        if n > 1:
            issues.append(BarIssue(sym, d, "duplicate", f"{n} rows for {d}"))

    per_year: dict[int, int] = defaultdict(int)
    for b in bars:
        per_year[b.date.year] += 1
    current = dt.date.today().year
    for year, n in sorted(per_year.items()):
        if year == current:
            continue                       # partial by definition
        if not (MIN_SESSIONS <= n <= MAX_SESSIONS):
            issues.append(BarIssue(sym, None, "count",
                                   f"{year} has {n} sessions"))

    ordered = sorted(bars, key=lambda b: b.date)
    for prev, cur in zip(ordered, ordered[1:]):
        if _business_days(prev.date, cur.date) > MAX_GAP_BUSINESS_DAYS:
            issues.append(BarIssue(sym, cur.date, "gap",
                                   f"{prev.date} -> {cur.date}"))
        if prev.close > 0:
            move = cur.close / prev.close - 1.0
            if abs(move) > EXTREME_MOVE:
                issues.append(BarIssue(sym, cur.date, "extreme",
                                       f"{move:+.1%} from {prev.date}"))
    return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_validate_bars.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add ebot/validate_bars.py tests/test_validate_bars.py
git commit -m "feat: bar data-integrity validation with fatal/warning split"
```

---

### Task 5c: Independent-source cross-check on event windows

**Files:**
- Create: `ebot/crosscheck.py`
- Test: `tests/test_crosscheck.py`

**Interfaces:**
- Consumes: `Bar` (Task 1), `Config` (Task 1)
- Produces: `parse_stooq_csv(text: str, symbol: str) -> list[Bar]`;
  `crosscheck_window(bars, ref_bars, dates, tol=0.005) -> list[BarIssue]`;
  `fetch_stooq(symbol, start, end, fetch=None) -> list[Bar]`

**Why an independent source.** The price cache and the event dates both arrive
through one vendor. A systematic adjustment error — a missed split, a wrong
dividend adjustment — would be invisible to internal validation because every
internal check would agree with itself. Stooq is free, needs no key, and is
independently sourced. Only **event windows** are cross-checked, not the whole
history: that is where a bad price changes a trade.

Tolerance is 0.5%, which absorbs legitimate vendor differences in dividend
adjustment while still catching a missed split (which shows up as ~50%+).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_crosscheck.py
import datetime as dt, pytest
from ebot.crosscheck import parse_stooq_csv, crosscheck_window, fetch_stooq
from ebot.types import Bar

CSV = """Date,Open,High,Low,Close,Volume
2020-01-02,100.0,101.0,99.0,100.5,1000000
2020-01-03,100.5,102.0,100.0,101.0,1100000
"""

def test_parses_stooq_csv():
    bars = parse_stooq_csv(CSV, "X")
    assert len(bars) == 2
    assert bars[0].date == dt.date(2020, 1, 2)
    assert bars[0].close == 100.5
    assert bars[1].volume == 1100000

def test_parse_ignores_blank_and_malformed_rows():
    bars = parse_stooq_csv(CSV + "\n\nN/A,N/A,N/A,N/A,N/A,N/A\n", "X")
    assert len(bars) == 2

def test_matching_prices_produce_no_issues():
    ours = parse_stooq_csv(CSV, "X")
    theirs = parse_stooq_csv(CSV, "X")
    assert crosscheck_window(ours, theirs, [dt.date(2020, 1, 2)]) == []

def test_small_difference_within_tolerance_ok():
    ours = parse_stooq_csv(CSV, "X")
    theirs = [Bar("X", b.date, b.open, b.high, b.low, b.close * 1.002, b.volume)
              for b in ours]
    assert crosscheck_window(ours, theirs, [dt.date(2020, 1, 2)]) == []

def test_missed_split_is_caught():
    ours = parse_stooq_csv(CSV, "X")
    theirs = [Bar("X", b.date, b.open, b.high, b.low, b.close * 4.0, b.volume)
              for b in ours]
    issues = crosscheck_window(ours, theirs, [dt.date(2020, 1, 2)])
    assert len(issues) == 1
    assert issues[0].kind == "crosscheck"
    assert "4" in issues[0].detail or "300" in issues[0].detail

def test_date_missing_from_reference_is_reported():
    ours = parse_stooq_csv(CSV, "X")
    issues = crosscheck_window(ours, [], [dt.date(2020, 1, 2)])
    assert issues and issues[0].kind == "crosscheck"

def test_fetch_stooq_builds_expected_url():
    seen = {}
    def fake(url):
        seen["url"] = url; return CSV
    fetch_stooq("AAPL", dt.date(2020, 1, 1), dt.date(2020, 12, 31), fetch=fake)
    assert "aapl.us" in seen["url"]
    assert "d1=20200101" in seen["url"] and "d2=20201231" in seen["url"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_crosscheck.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebot.crosscheck'`

- [ ] **Step 3: Write minimal implementation**

```python
# ebot/crosscheck.py
import csv, io, datetime as dt, time, urllib.request
from ebot.types import Bar
from ebot.validate_bars import BarIssue

STOOQ = ("https://stooq.com/q/d/l/?s={sym}.us&d1={d1}&d2={d2}&i=d")
_last = [0.0]

def _fetch(url: str) -> str:
    elapsed = time.monotonic() - _last[0]
    if elapsed < 0.5:
        time.sleep(0.5 - elapsed)
    _last[0] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "ebot-research"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()

def parse_stooq_csv(text: str, symbol: str) -> list[Bar]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            out.append(Bar(symbol=symbol,
                           date=dt.date.fromisoformat(row["Date"]),
                           open=float(row["Open"]), high=float(row["High"]),
                           low=float(row["Low"]), close=float(row["Close"]),
                           volume=int(float(row["Volume"]))))
        except (ValueError, TypeError, KeyError):
            continue                       # blank or N/A row
    return sorted(out, key=lambda b: b.date)

def fetch_stooq(symbol: str, start: dt.date, end: dt.date, fetch=None) -> list[Bar]:
    fetch = fetch or _fetch
    url = STOOQ.format(sym=symbol.lower(),
                       d1=start.strftime("%Y%m%d"), d2=end.strftime("%Y%m%d"))
    return parse_stooq_csv(fetch(url), symbol)

def crosscheck_window(bars: list[Bar], ref_bars: list[Bar],
                      dates: list[dt.date], tol: float = 0.005) -> list[BarIssue]:
    ours = {b.date: b for b in bars}
    theirs = {b.date: b for b in ref_bars}
    issues = []
    for d in dates:
        a, b = ours.get(d), theirs.get(d)
        if a is None:
            continue                       # not our data's problem here
        if b is None:
            issues.append(BarIssue(a.symbol, d, "crosscheck",
                                   "date absent from reference source"))
            continue
        if b.close <= 0:
            continue
        diff = abs(a.close / b.close - 1.0)
        if diff > tol:
            issues.append(BarIssue(a.symbol, d, "crosscheck",
                f"close {a.close} vs reference {b.close} ({diff:.1%} apart)"))
    return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_crosscheck.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add ebot/crosscheck.py tests/test_crosscheck.py
git commit -m "feat: independent-source cross-check on event windows"
```

---

### Task 6: Entry-timing rule (spec 6.1)

**Files:**
- Create: `ebot/calendar.py`
- Test: `tests/test_calendar.py`

**Interfaces:**
- Consumes: `Bar` (Task 1)
- Produces: `sessions_from_bars(bars: list[Bar]) -> list[dt.date]`; `resolve_timing(accepted_at: dt.datetime, sessions: list[dt.date]) -> tuple[dt.date, dt.date] | None` returning `(t0, t1)` where t1 is the observation bar. **Per spec 6.1 the entry price is t1's CLOSE**; this function returns the date only.

This is the highest-risk function in Phase 0 — an off-by-one here silently corrupts every result. The spec's three cases are tested exhaustively plus boundary times.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar.py
import datetime as dt, pytest
from zoneinfo import ZoneInfo
from ebot.calendar import resolve_timing, sessions_from_bars
from ebot.types import Bar

ET = ZoneInfo("US/Eastern")
# Mon 2024-05-06 .. Fri 2024-05-10, then Mon 2024-05-13
SESSIONS = [dt.date(2024,5,6), dt.date(2024,5,7), dt.date(2024,5,8),
            dt.date(2024,5,9), dt.date(2024,5,10), dt.date(2024,5,13)]

def at(y,m,d,h,mi):
    return dt.datetime(y,m,d,h,mi,tzinfo=ET)

def test_post_close_filing_enters_next_session():
    # Wed 16:05 -> T0 = Wed, entry = Thu
    assert resolve_timing(at(2024,5,8,16,5), SESSIONS) == (dt.date(2024,5,8), dt.date(2024,5,9))

def test_intraday_filing_forgoes_same_day():
    # Wed 11:00 -> T0 = Wed, entry = Thu (conservative)
    assert resolve_timing(at(2024,5,8,11,0), SESSIONS) == (dt.date(2024,5,8), dt.date(2024,5,9))

def test_pre_open_filing_enters_same_day():
    # Wed 07:30 -> T0 = Tue (prior session), entry = Wed
    assert resolve_timing(at(2024,5,8,7,30), SESSIONS) == (dt.date(2024,5,7), dt.date(2024,5,8))

def test_exactly_0930_counts_as_intraday():
    assert resolve_timing(at(2024,5,8,9,30), SESSIONS) == (dt.date(2024,5,8), dt.date(2024,5,9))

def test_exactly_1600_counts_as_post_close():
    assert resolve_timing(at(2024,5,8,16,0), SESSIONS) == (dt.date(2024,5,8), dt.date(2024,5,9))

def test_friday_post_close_skips_weekend():
    assert resolve_timing(at(2024,5,10,17,0), SESSIONS) == (dt.date(2024,5,10), dt.date(2024,5,13))

def test_filing_on_non_session_day_rolls_forward():
    # Saturday 2024-05-11 -> T0 = Fri, entry = Mon
    assert resolve_timing(at(2024,5,11,10,0), SESSIONS) == (dt.date(2024,5,10), dt.date(2024,5,13))

def test_returns_none_when_no_following_session():
    assert resolve_timing(at(2024,5,13,17,0), SESSIONS) is None

def test_returns_none_when_no_prior_session():
    assert resolve_timing(at(2024,5,6,7,0), SESSIONS) is None

def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        resolve_timing(dt.datetime(2024,5,8,11,0), SESSIONS)

def test_sessions_from_bars_sorted_unique():
    bars = [Bar("AAPL", dt.date(2024,5,8),1,1,1,1,1),
            Bar("AAPL", dt.date(2024,5,6),1,1,1,1,1)]
    assert sessions_from_bars(bars) == [dt.date(2024,5,6), dt.date(2024,5,8)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_calendar.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebot.calendar'`

- [ ] **Step 3: Write minimal implementation**

```python
# ebot/calendar.py
import bisect, datetime as dt
from zoneinfo import ZoneInfo
from ebot.types import Bar

ET = ZoneInfo("US/Eastern")
OPEN, CLOSE = dt.time(9, 30), dt.time(16, 0)

def sessions_from_bars(bars: list[Bar]) -> list[dt.date]:
    return sorted({b.date for b in bars})

def _prev_session(d: dt.date, sessions: list[dt.date]) -> dt.date | None:
    i = bisect.bisect_left(sessions, d)
    return sessions[i - 1] if i > 0 else None

def _next_session(d: dt.date, sessions: list[dt.date]) -> dt.date | None:
    i = bisect.bisect_right(sessions, d)
    return sessions[i] if i < len(sessions) else None

def resolve_timing(accepted_at: dt.datetime,
                   sessions: list[dt.date]) -> tuple[dt.date, dt.date] | None:
    """Spec 6.1. Returns (t0, entry_date) or None if unresolvable."""
    if accepted_at.tzinfo is None:
        raise ValueError("accepted_at must be timezone-aware")
    et = accepted_at.astimezone(ET)
    d, t = et.date(), et.time()
    is_session = d in set(sessions)

    if is_session and t < OPEN:
        t0 = _prev_session(d, sessions)          # pre-open: T0 is prior session
        entry = d
    else:
        # intraday, post-close, or non-session day: T0 is the session at/before d
        t0 = d if is_session else _prev_session(d, sessions)
        entry = _next_session(t0, sessions) if t0 else None
    if t0 is None or entry is None:
        return None
    return (t0, entry)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_calendar.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add ebot/calendar.py tests/test_calendar.py
git commit -m "feat: entry-timing rule per spec 6.1 with exhaustive case tests"
```

---

### Task 7: Gate conditions G1-G5 (spec 6.2)

**Files:**
- Create: `ebot/gate.py`
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: `Bar` (Task 1), `Config` (Task 1)
- Produces: `passes_gate(bars: list[Bar], t0: dt.date, entry: dt.date, cfg: Config) -> tuple[bool, dict[str, bool]]` — returns `(all_pass, {"G1": bool, ..., "G5": bool})`, or `(False, {})` when history is insufficient

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gate.py
import datetime as dt
from pathlib import Path
from ebot.gate import passes_gate
from ebot.config import load_config
from ebot.types import Bar

CFG = load_config(Path("config.example.yaml"))

def series(n=60, close=100.0, vol=1_000_000):
    """n flat sessions ending 2024-05-08, then caller appends the entry bar."""
    start = dt.date(2024, 1, 2)
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(Bar("X", d, close, close, close, close, vol))
        d += dt.timedelta(days=1)
    return out

def with_event(gap_pct, t0_vol_mult=2.0, t0_close=100.0, sma_ok=True):
    bars = series()
    t0 = bars[-1]
    bars[-1] = Bar("X", t0.date, t0_close, t0_close, t0_close, t0_close,
                   int(1_000_000 * t0_vol_mult))
    entry_date = t0.date + dt.timedelta(days=1)
    entry_open = t0_close * (1 + gap_pct / 100.0)
    bars.append(Bar("X", entry_date, entry_open, entry_open, entry_open, entry_open, 1_000_000))
    return bars, t0.date, entry_date

def test_passes_when_all_conditions_met():
    bars, t0, entry = with_event(gap_pct=3.0)
    ok, detail = passes_gate(bars, t0, entry, CFG)
    assert ok is True
    assert all(detail.values())

def test_g1_fails_on_small_gap():
    bars, t0, entry = with_event(gap_pct=0.5)
    ok, detail = passes_gate(bars, t0, entry, CFG)
    assert ok is False and detail["G1"] is False

def test_g2_fails_on_negative_gap():
    bars, t0, entry = with_event(gap_pct=-3.0)
    ok, detail = passes_gate(bars, t0, entry, CFG)
    assert ok is False and detail["G2"] is False

def test_g3_fails_on_normal_volume():
    bars, t0, entry = with_event(gap_pct=3.0, t0_vol_mult=1.0)
    ok, detail = passes_gate(bars, t0, entry, CFG)
    assert ok is False and detail["G3"] is False

def test_g4_fails_on_thin_liquidity():
    bars, t0, entry = with_event(gap_pct=3.0, t0_close=1.0)
    ok, detail = passes_gate(bars, t0, entry, CFG)
    assert ok is False and detail["G4"] is False

def test_insufficient_history_returns_false_not_partial():
    bars, t0, entry = with_event(gap_pct=3.0)
    ok, detail = passes_gate(bars[-5:], t0, entry, CFG)
    assert ok is False and detail == {}

def test_gate_uses_no_bars_at_or_after_entry():
    """Poisoning post-entry bars must not change the verdict."""
    bars, t0, entry = with_event(gap_pct=3.0)
    base, _ = passes_gate(bars, t0, entry, CFG)
    poisoned = bars + [Bar("X", entry + dt.timedelta(days=i), 1e9, 1e9, 1e9, 1e9, 1)
                       for i in range(1, 6)]
    after, _ = passes_gate(poisoned, t0, entry, CFG)
    assert base == after
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebot.gate'`

- [ ] **Step 3: Write minimal implementation**

```python
# ebot/gate.py
import datetime as dt
from statistics import median
from ebot.config import Config
from ebot.types import Bar

def passes_gate(bars: list[Bar], t0: dt.date, entry: dt.date,
                cfg: Config) -> tuple[bool, dict[str, bool]]:
    by_date = {b.date: b for b in bars}
    if t0 not in by_date or entry not in by_date:
        return False, {}
    prior = [b for b in bars if b.date < t0]
    if len(prior) < max(cfg.lookback_sessions, cfg.sma_window):
        return False, {}

    t0_bar, entry_bar = by_date[t0], by_date[entry]
    window = prior[-cfg.lookback_sessions:]
    sma = sum(b.close for b in prior[-cfg.sma_window:]) / cfg.sma_window
    gap = entry_bar.open / t0_bar.close - 1.0

    checks = {
        "G1": abs(gap) >= cfg.gap_min_pct / 100.0,
        "G2": entry_bar.open > t0_bar.close,
        "G3": t0_bar.volume >= cfg.volume_mult * median(b.volume for b in window),
        "G4": median(b.close * b.volume for b in window) >= cfg.min_dollar_volume,
        "G5": t0_bar.close <= cfg.extended_mult * sma,
    }
    return all(checks.values()), checks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gate.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add ebot/gate.py tests/test_gate.py
git commit -m "feat: gate conditions G1-G5 with look-ahead isolation test"
```

---

### Task 8: Backtest engine

**Files:**
- Create: `ebot/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `resolve_timing` (Task 6), `passes_gate` (Task 7), `Event`/`Bar`/`Trade` (Task 1)
- Produces: `build_trade(event, bars, bench_bars, cfg) -> Trade | None`; `run_events(events, bars_by_symbol, bench_bars, cfg) -> list[Trade]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest.py
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
from ebot.backtest import build_trade, run_events
from ebot.config import load_config
from ebot.types import Bar, Event
from tests.test_gate import with_event   # reuse the fixture builder

ET = ZoneInfo("US/Eastern")
CFG = load_config(Path("config.example.yaml"))

def extend(bars, n, start_px):
    """Append n sessions rising 1% per session."""
    out, d, px = list(bars), bars[-1].date, start_px
    for _ in range(n):
        d += dt.timedelta(days=1)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        px *= 1.01
        out.append(Bar(bars[-1].symbol, d, px, px, px, px, 1_000_000))
    return out

def test_builds_trade_with_t3_exit():
    bars, t0, entry = with_event(gap_pct=3.0)
    bars = extend(bars, 4, bars[-1].close)
    ev = Event("X", "0000000001", "acc-1",
               dt.datetime.combine(t0, dt.time(16, 30), tzinfo=ET))
    bench = [Bar("SPY", b.date, 400, 400, 400, 400, 1) for b in bars]
    tr = build_trade(ev, bars, bench, CFG)
    assert tr is not None
    assert tr.entry_date == entry
    assert tr.exit_date == sorted(b.date for b in bars if b.date > entry)[CFG.hold_days - 1]
    assert tr.entry_px == next(b.close for b in bars if b.date == entry), \
        "spec 6.1: entry price is the T+1 CLOSE, not the open"
    assert tr.ret > 0
    assert tr.excess == tr.ret - tr.spy_ret

def test_returns_none_when_gate_fails():
    bars, t0, entry = with_event(gap_pct=0.2)
    bars = extend(bars, 4, bars[-1].close)
    ev = Event("X", "0000000001", "acc-1",
               dt.datetime.combine(t0, dt.time(16, 30), tzinfo=ET))
    bench = [Bar("SPY", b.date, 400, 400, 400, 400, 1) for b in bars]
    assert build_trade(ev, bars, bench, CFG) is None

def test_returns_none_when_exit_bar_missing():
    bars, t0, entry = with_event(gap_pct=3.0)   # no bars after entry
    ev = Event("X", "0000000001", "acc-1",
               dt.datetime.combine(t0, dt.time(16, 30), tzinfo=ET))
    bench = [Bar("SPY", b.date, 400, 400, 400, 400, 1) for b in bars]
    assert build_trade(ev, bars, bench, CFG) is None

def test_excess_is_zero_when_stock_matches_benchmark():
    bars, t0, entry = with_event(gap_pct=3.0)
    bars = extend(bars, 4, bars[-1].close)
    bench = [Bar("SPY", b.date, b.open, b.high, b.low, b.close, 1) for b in bars]
    ev = Event("X", "0000000001", "acc-1",
               dt.datetime.combine(t0, dt.time(16, 30), tzinfo=ET))
    tr = build_trade(ev, bars, bench, CFG)
    assert abs(tr.excess) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backtest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebot.backtest'`

- [ ] **Step 3: Write minimal implementation**

```python
# ebot/backtest.py
import datetime as dt
from ebot.calendar import resolve_timing, sessions_from_bars
from ebot.config import Config
from ebot.gate import passes_gate
from ebot.types import Bar, Event, Trade

def _ret(bars: dict[dt.date, Bar], entry: dt.date, exit_: dt.date) -> float | None:
    """Close-to-close. Spec 6.1: entry is the T+1 CLOSE, not the open."""
    if entry not in bars or exit_ not in bars:
        return None
    return bars[exit_].close / bars[entry].close - 1.0

def build_trade(event: Event, bars: list[Bar], bench_bars: list[Bar],
                cfg: Config) -> Trade | None:
    sessions = sessions_from_bars(bars)
    timing = resolve_timing(event.accepted_at, sessions)
    if timing is None:
        return None
    t0, entry = timing
    ok, _ = passes_gate(bars, t0, entry, cfg)
    if not ok:
        return None
    after = [d for d in sessions if d > entry]
    if len(after) < cfg.hold_days:
        return None
    exit_ = after[cfg.hold_days - 1]

    by_date = {b.date: b for b in bars}
    bench_by_date = {b.date: b for b in bench_bars}
    r = _ret(by_date, entry, exit_)
    br = _ret(bench_by_date, entry, exit_)
    if r is None or br is None:
        return None
    return Trade(ticker=event.ticker, accepted_at=event.accepted_at, t0=t0,
                 entry_date=entry, exit_date=exit_,
                 entry_px=by_date[entry].close, exit_px=by_date[exit_].close,
                 ret=r, spy_ret=br, excess=r - br)

def run_events(events: list[Event], bars_by_symbol: dict[str, list[Bar]],
               bench_bars: list[Bar], cfg: Config) -> list[Trade]:
    out = []
    for ev in events:
        bars = bars_by_symbol.get(ev.ticker)
        if not bars:
            continue
        tr = build_trade(ev, bars, bench_bars, cfg)
        if tr:
            out.append(tr)
    return sorted(out, key=lambda t: t.entry_date)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backtest.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add ebot/backtest.py tests/test_backtest.py
git commit -m "feat: backtest engine, T+1 open entry to T+3 close exit"
```

---

### Task 9: Statistics and success criteria (spec 7.4)

**Files:**
- Create: `ebot/stats.py`
- Test: `tests/test_stats.py`

**Interfaces:**
- Consumes: nothing beyond stdlib
- Produces: `t_stat(xs) -> float`; `hit_rate(xs) -> float`; `max_drawdown(xs) -> float`; `evaluate(xs) -> dict` with keys `n, mean, t_stat, hit_rate, max_drawdown, passes_t, passes_hit, passes_dd, passes_all`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stats.py
import math, pytest
from ebot.stats import t_stat, hit_rate, max_drawdown, evaluate

def test_t_stat_zero_for_symmetric_data():
    assert abs(t_stat([-1.0, 1.0, -1.0, 1.0])) < 1e-9

def test_t_stat_positive_for_consistent_gains():
    assert t_stat([0.01, 0.012, 0.009, 0.011, 0.010]) > 2.0

def test_t_stat_needs_two_points():
    assert t_stat([0.01]) == 0.0
    assert t_stat([]) == 0.0

def test_t_stat_zero_variance_returns_zero():
    assert t_stat([0.01, 0.01, 0.01]) == 0.0

def test_hit_rate():
    assert hit_rate([1.0, -1.0, 1.0, 1.0]) == 0.75
    assert hit_rate([]) == 0.0

def test_max_drawdown_on_compounded_equity():
    # +10% then -50% then +10%: peak 1.10, trough 0.55 -> 50% drawdown
    assert abs(max_drawdown([0.10, -0.50, 0.10]) - 0.50) < 1e-9

def test_max_drawdown_zero_when_monotonic():
    assert max_drawdown([0.01, 0.01, 0.01]) == 0.0

def test_evaluate_fails_when_any_criterion_fails():
    r = evaluate([0.01, -0.02, 0.03, -0.04])
    assert r["passes_all"] is False

def test_evaluate_reports_all_three_flags():
    r = evaluate([0.01] * 10)
    assert set(["passes_t", "passes_hit", "passes_dd", "passes_all"]) <= set(r)
    assert r["n"] == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stats.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebot.stats'`

- [ ] **Step 3: Write minimal implementation**

```python
# ebot/stats.py
import math
from statistics import fmean, stdev

T_THRESHOLD, HIT_THRESHOLD, DD_THRESHOLD = 2.0, 0.50, 0.25

def t_stat(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    s = stdev(xs)
    if s == 0.0:
        return 0.0
    return fmean(xs) / (s / math.sqrt(len(xs)))

def hit_rate(xs: list[float]) -> float:
    return sum(1 for x in xs if x > 0) / len(xs) if xs else 0.0

def max_drawdown(xs: list[float]) -> float:
    """Max peak-to-trough decline of the compounded equity curve."""
    equity, peak, worst = 1.0, 1.0, 0.0
    for x in xs:
        equity *= (1.0 + x)
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
    return worst

def evaluate(xs: list[float]) -> dict:
    t, h, d = t_stat(xs), hit_rate(xs), max_drawdown(xs)
    passes = {"passes_t": t >= T_THRESHOLD,
              "passes_hit": h > HIT_THRESHOLD,
              "passes_dd": d <= DD_THRESHOLD}
    return {"n": len(xs), "mean": fmean(xs) if xs else 0.0,
            "t_stat": t, "hit_rate": h, "max_drawdown": d,
            **passes, "passes_all": all(passes.values())}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stats.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add ebot/stats.py tests/test_stats.py
git commit -m "feat: t-stat, hit rate, drawdown, and spec 7.4 criteria"
```

---

### Task 10: Look-ahead integrity control (spec 11.3)

**Files:**
- Create: `tests/test_integrity.py`

**Interfaces:**
- Consumes: `run_events` (Task 8), `evaluate` (Task 9)
- Produces: no production code — this is a control that must fail loudly if the pipeline leaks future information

The shuffled-labels test is the single most important test in Phase 0. If randomized event dates produce an edge, there is a look-ahead bug and every real result is meaningless.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_integrity.py
import datetime as dt, random
from pathlib import Path
from zoneinfo import ZoneInfo
from ebot.backtest import run_events
from ebot.config import load_config
from ebot.stats import evaluate
from ebot.types import Bar, Event

ET = ZoneInfo("US/Eastern")
CFG = load_config(Path("config.example.yaml"))

def random_walk(symbol, n=900, seed=7):
    rnd = random.Random(seed)
    out, d, px = [], dt.date(2020, 1, 2), 100.0
    while len(out) < n:
        if d.weekday() < 5:
            px *= (1 + rnd.gauss(0, 0.02))
            out.append(Bar(symbol, d, px, px * 1.01, px * 0.99, px,
                           rnd.randint(5_000_000, 20_000_000)))
        d += dt.timedelta(days=1)
    return out

def test_shuffled_labels_produce_no_edge():
    """Random event dates on a random walk must show no edge.
    If this fails, the pipeline is leaking future information."""
    bars = random_walk("X")
    raw = random_walk("SPY", seed=99)
    # Independent price path, but dates aligned to the stock's sessions.
    bench = [Bar("SPY", stock.date, b.open, b.high, b.low, b.close, b.volume)
             for stock, b in zip(bars, raw)]
    rnd = random.Random(42)
    dates = sorted({b.date for b in bars})[60:-10]
    events = [Event("X", "0000000001", f"acc-{i}",
                    dt.datetime.combine(rnd.choice(dates), dt.time(16, 30), tzinfo=ET))
              for i in range(300)]
    trades = run_events(events, {"X": bars}, bench, CFG)
    result = evaluate([t.excess for t in trades])
    assert result["n"] > 0, "control produced no trades; fixture is wrong"
    assert abs(result["t_stat"]) < 2.0, (
        f"LOOK-AHEAD BUG: random events show t={result['t_stat']:.2f}")

def test_gate_inputs_never_include_entry_day_close():
    """Mutating the entry bar's close/high/low must not change gate outcome.
    Only the entry OPEN is legitimately knowable at entry."""
    from ebot.gate import passes_gate
    from ebot.calendar import sessions_from_bars, resolve_timing
    bars = random_walk("X")
    sessions = sessions_from_bars(bars)
    t0, entry = resolve_timing(
        dt.datetime.combine(sessions[200], dt.time(16, 30), tzinfo=ET), sessions)
    before, _ = passes_gate(bars, t0, entry, CFG)
    mutated = [Bar(b.symbol, b.date, b.open, 1e9, 0.0, 1e9, b.volume)
               if b.date == entry else b for b in bars]
    after, _ = passes_gate(mutated, t0, entry, CFG)
    assert before == after, "gate reads entry-day data beyond the open"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_integrity.py -v`
Expected: FAIL — `tests/test_integrity.py` does not yet exist; after creation both tests must pass against the Task 6-9 implementations. If `test_shuffled_labels_produce_no_edge` fails, **stop and debug the pipeline** — do not proceed to Task 11.

- [ ] **Step 3: No production code required**

These tests validate existing behavior. If either fails, fix the module it implicates (`gate.py` or `backtest.py`), not the test.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ -v`
Expected: all tests pass, including both integrity controls

- [ ] **Step 5: Commit**

```bash
git add tests/test_integrity.py
git commit -m "test: shuffled-label and entry-day look-ahead controls"
```

---

### Task 11: Runner, train/test split, and the run-once report

**Files:**
- Create: `ebot/run_backtest.py`, `README.md`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: everything above
- Produces: `split_trades(trades, boundary) -> tuple[list[Trade], list[Trade]]`; `main(argv) -> int`; writes `reports/backtest-<date>.json` and prints a human summary

**Run-once discipline:** the runner refuses to overwrite an existing report for the same config hash. Re-running after seeing results requires deleting the report by hand, which makes §7.3 violations deliberate and visible rather than accidental.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner.py
import datetime as dt, json, pytest
from pathlib import Path
from ebot.run_backtest import split_trades, write_report
from ebot.types import Trade

def mk(d):
    return Trade("X", dt.datetime(2020,1,1,tzinfo=dt.timezone.utc), d, d, d,
                 1.0, 1.1, 0.1, 0.05, 0.05)

def test_split_is_by_time_not_random():
    trades = [mk(dt.date(2020,6,1)), mk(dt.date(2021,1,1)), mk(dt.date(2022,3,1))]
    train, test = split_trades(trades, dt.date(2021,1,1))
    assert [t.entry_date for t in train] == [dt.date(2020,6,1)]
    assert len(test) == 2, "boundary date belongs to the TEST set"

def test_write_report_refuses_overwrite(tmp_path):
    p = tmp_path / "r.json"
    write_report(p, {"a": 1})
    with pytest.raises(FileExistsError):
        write_report(p, {"a": 2})
    assert json.loads(p.read_text())["a"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebot.run_backtest'`

- [ ] **Step 3: Write minimal implementation**

```python
# ebot/run_backtest.py
import argparse, datetime as dt, json, sys
from pathlib import Path
from ebot.backtest import run_events
from ebot.config import load_config
from ebot.edgar import fetch_events
from ebot.prices import load_bars, fetch_all_years
from ebot.validate_bars import validate_bars, FATAL_KINDS
from ebot.stats import evaluate
from ebot.types import Trade

def split_trades(trades: list[Trade], boundary: dt.date) -> tuple[list[Trade], list[Trade]]:
    train = [t for t in trades if t.entry_date < boundary]
    test = [t for t in trades if t.entry_date >= boundary]
    return train, test

def write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(
            f"{path} exists. Spec 7.3 forbids re-running to improve results. "
            f"Delete it by hand if you genuinely intend to re-run.")
    path.write_text(json.dumps(payload, indent=2, default=str))

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=Path("config.yaml"))
    ap.add_argument("--fetch", action="store_true", help="refresh price cache")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)

    symbols = list(cfg.whitelist) + [cfg.benchmark]
    if args.fetch:
        for s in symbols:
            print(f"fetching {s}...", file=sys.stderr)
            fetch_all_years(s, cfg)

    bars = {s: load_bars(s, cfg) for s in symbols}
    missing = [s for s, b in bars.items() if not b]
    if missing:
        print(f"no cached bars for {missing}; run with --fetch", file=sys.stderr)
        return 1

    # Task 5b: refuse to backtest on structurally impossible data.
    all_issues = [i for s in symbols for i in validate_bars(bars[s], cfg)]
    fatal = [i for i in all_issues if i.kind in FATAL_KINDS]
    for i in all_issues:
        print(f"  [{i.kind}] {i.symbol} {i.date}: {i.detail}", file=sys.stderr)
    if fatal:
        print(f"\n{len(fatal)} FATAL data issues. Refusing to backtest on "
              f"bad data. Fix the cache and re-run.", file=sys.stderr)
        return 2
    if all_issues:
        print(f"{len(all_issues)} non-fatal data warnings (see above).",
              file=sys.stderr)

    events = []
    for t in cfg.whitelist:
        events.extend(fetch_events(t, cfg))
    trades = run_events(events, bars, bars[cfg.benchmark], cfg)
    train, test = split_trades(trades, cfg.train_test_split)

    # Spec 6.4: buy-and-hold comparison over the same test window.
    bench_bars = bars[cfg.benchmark]
    held = [b for b in bench_bars if b.date >= cfg.train_test_split]
    buy_hold = (held[-1].close / held[0].open - 1.0) if len(held) > 1 else 0.0
    test_eval = evaluate([t.excess for t in test])
    strat_total = 1.0
    for t in test:
        strat_total *= (1.0 + t.ret)

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "n_events": len(events), "n_trades": len(trades),
        "train": evaluate([t.excess for t in train]),
        "test": test_eval,
        "buy_and_hold": {
            "symbol": cfg.benchmark,
            "window_start": held[0].date.isoformat() if held else None,
            "total_return": buy_hold,
            "strategy_total_return": strat_total - 1.0,
        },
        "data_warnings": [
            {"symbol": i.symbol, "date": str(i.date), "kind": i.kind,
             "detail": i.detail} for i in all_issues
        ],
        "known_limitations": {
            "survivorship_bias": (
                "The whitelist is 12 names that are large and liquid TODAY. "
                "Backtesting them over 2014+ inflates returns because their "
                "survival and growth is known in advance. Spec 11.3: disclosed, "
                "not corrected."),
            "statistical_power": (
                "Spec 7.5: at this sample size only a large edge is detectable. "
                "A negative verdict means 'no large edge detectable', not "
                "'no edge exists'."),
        },
    }
    write_report(Path("reports") / f"backtest-{dt.date.today()}.json", payload)

    r = payload["test"]
    print(f"\nEvents: {len(events)}  Trades: {len(trades)}  "
          f"Train: {len(train)}  Test: {r['n']}")
    print(f"TEST  mean excess {r['mean']:+.4%}  t={r['t_stat']:.2f}  "
          f"hit={r['hit_rate']:.1%}  maxDD={r['max_drawdown']:.1%}")
    bh = payload["buy_and_hold"]
    print(f"Strategy total {bh['strategy_total_return']:+.2%} vs "
          f"buy-and-hold {bh['symbol']} {bh['total_return']:+.2%}")
    print(f"\nVERDICT: {'EDGE DETECTED' if r['passes_all'] else 'NO EDGE'}")
    if not r["passes_all"]:
        failed = [k for k in ("passes_t", "passes_hit", "passes_dd") if not r[k]]
        print(f"failed criteria: {', '.join(failed)}")
        print("Per spec 7.3, do NOT adjust parameters and re-run.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

Then create `README.md` with exactly this content:

````markdown
# ebot — Phase 0: Earnings Signal Backtest

**This code places no orders.** Phase 0 is read-only research. The live
trading system (Phases 1-3) is specified but NOT built, and will only be
built if this backtest clears the bar in spec §7.4.

## Setup

```bash
pip install -e ".[dev]"
cp config.example.yaml config.yaml
# edit config.yaml: set sec_user_agent to a real name and email.
# SEC requires this and will block requests without it.
```

## Run

```bash
python -m ebot.run_backtest --fetch   # first run: populates the price cache
python -m ebot.run_backtest           # later runs: cache-only
pytest tests/ -v                      # full suite incl. look-ahead controls
```

`--fetch` shells out to `claude -p` once per symbol with an allowlist
containing only `get_equity_historicals`. No order tool is reachable.

## Reading the result

The runner prints a VERDICT and writes `reports/backtest-<date>.json`.

**It refuses to overwrite an existing report.** This is deliberate: spec
§7.3 forbids re-running with adjusted parameters to improve results. If you
delete the report to re-run, you are knowingly departing from the
pre-registered protocol.

A NO EDGE verdict means *no large edge is detectable at this sample size*
(spec §7.5) — not that no edge exists. Results are also inflated by
survivorship bias in the fixed whitelist (spec §11.3).

## Layout

| File | Responsibility |
|------|----------------|
| `ebot/edgar.py` | SEC 8-K Item 2.02 acceptance timestamps |
| `ebot/prices.py` | Daily OHLCV via headless Claude, cached |
| `ebot/calendar.py` | Entry-timing rule (spec §6.1) |
| `ebot/gate.py` | Gate conditions G1-G5 (spec §6.2) |
| `ebot/backtest.py` | Event to trade, T+1 open to T+3 close |
| `ebot/stats.py` | t-stat, hit rate, drawdown, §7.4 criteria |

## Revoking broker access

`/mcp` in Claude Code disconnects `robinhood-trading`; revoke the agentic
connection in the Robinhood app under account settings.
````

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add ebot/run_backtest.py tests/test_runner.py README.md
git commit -m "feat: backtest runner with time-based split and run-once guard"
```

---

## After Task 11

Run the backtest **once**:

```bash
python -m ebot.run_backtest --fetch
```

Report the test-set numbers as they come out. If the verdict is NO EDGE, that is
the Phase 0 deliverable — write up the finding and stop. Phase 1 is not built.
Per spec §7.3 and §7.5, do not adjust parameters and re-run, and do not expand
the whitelist reactively.
