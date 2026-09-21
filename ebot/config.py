from pathlib import Path
import datetime as dt
import yaml
from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    whitelist: list[str] = Field(min_length=1)
    sec_user_agent: str
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
