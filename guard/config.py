from pathlib import Path
from pydantic import BaseModel, Field, field_validator, model_validator
import yaml

MODES = {"paper", "live"}
SCHEDULES = {"weekly", "monthly"}


class Config(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    account_number: str = Field(min_length=1)
    symbol: str
    amount_usd: float = Field(gt=0)
    mode: str = "paper"
    schedule: str = "weekly"
    whitelist: list[str] = ["VTI", "VOO", "SPY", "ITOT", "IVV", "BND", "AOR"]
    max_order_usd: float = Field(default=50.0, gt=0)
    max_spend_per_period_usd: float = Field(default=50.0, gt=0)
    max_lifetime_spend_usd: float = Field(default=500.0, gt=0)
    open_buffer_minutes: int = Field(default=15, ge=0)
    close_buffer_minutes: int = Field(default=10, ge=0)
    ledger_dir: Path = Path(".")

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("whitelist")
    @classmethod
    def _wl(cls, v: list[str]) -> list[str]:
        out = [s.strip().upper() for s in v]
        if not out:
            raise ValueError("whitelist must not be empty")
        return out

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in MODES:
            raise ValueError(f"mode must be one of {sorted(MODES)}")
        return v

    @field_validator("schedule")
    @classmethod
    def _sched(cls, v: str) -> str:
        if v not in SCHEDULES:
            raise ValueError(f"schedule must be one of {sorted(SCHEDULES)}")
        return v

    @model_validator(mode="after")
    def _coherent(self):
        if self.symbol not in self.whitelist:
            raise ValueError(f"symbol {self.symbol} is not in the whitelist")
        if self.amount_usd > self.max_order_usd:
            raise ValueError("amount_usd exceeds max_order_usd")
        if self.amount_usd > self.max_spend_per_period_usd:
            raise ValueError("amount_usd exceeds max_spend_per_period_usd")
        if self.max_lifetime_spend_usd < self.max_spend_per_period_usd:
            raise ValueError("lifetime cap is below the per-period cap")
        return self

    @property
    def ledger_path(self) -> Path:
        """Separate ledger per mode: paper spending must never consume the
        live lifetime cap."""
        return Path(self.ledger_dir) / f"ledger-{self.mode}.jsonl"


def load_config(path: Path = Path("guard.yaml")) -> Config:
    return Config(**(yaml.safe_load(Path(path).read_text()) or {}))
