"""Options-mode configuration. Separate from the DCA Config: different
instrument, different caps, different failure modes."""
from pathlib import Path
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class OptionConfig(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    account_number: str = Field(min_length=1)
    mode: str = "paper"
    underlyings: list[str] = ["XLU", "XLF", "SLV", "EWZ", "EEM", "TLT"]

    # caps -- position size scales with account value between the two bounds
    min_position_usd: float = Field(default=50.0, gt=0)
    max_position_usd: float = Field(default=100.0, gt=0)
    position_fraction: float = Field(default=0.33, gt=0, le=1)
    max_open_positions: int = Field(default=2, gt=0)
    # Dead-man's switch: cumulative gross deployed. Not a loss limit -- you can
    # only lose what you deposit. It guarantees a human is eventually forced
    # back into the loop however long the tool is left alone.
    max_lifetime_usd: float = Field(default=2000.0, gt=0)

    # exits -- deterministic, never delegated to the analyst
    take_profit_pct: float = Field(default=50.0, gt=0)
    stop_loss_pct: float = Field(default=50.0, gt=0, le=100)
    close_at_dte: int = Field(default=14, ge=1)

    # entry filters
    min_dte: int = Field(default=30, ge=1)
    max_dte: int = Field(default=45, ge=1)
    target_delta: float = Field(default=0.30, gt=0, lt=1)
    delta_tolerance: float = Field(default=0.15, gt=0, lt=1)
    max_spread_pct_of_mid: float = Field(default=15.0, gt=0)
    min_open_interest: int = Field(default=100, ge=0)

    cadence_minutes: int = Field(default=15, gt=0)
    open_buffer_minutes: int = Field(default=15, ge=0)
    close_buffer_minutes: int = Field(default=10, ge=0)
    ledger_dir: Path = Path(".")

    @field_validator("underlyings")
    @classmethod
    def _up(cls, v: list[str]) -> list[str]:
        out = [s.strip().upper() for s in v]
        if not out:
            raise ValueError("underlyings must not be empty")
        if len(set(out)) != len(out):
            raise ValueError("duplicate underlying")
        return out

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in {"paper", "live"}:
            raise ValueError("mode must be paper or live")
        return v

    @model_validator(mode="after")
    def _coherent(self):
        if self.min_dte > self.max_dte:
            raise ValueError("min_dte above max_dte")
        if self.close_at_dte >= self.min_dte:
            raise ValueError("close_at_dte must be below min_dte, or a new "
                             "position would be closed immediately")
        if self.min_position_usd > self.max_position_usd:
            raise ValueError("min_position_usd above max_position_usd")
        if self.max_position_usd > self.max_lifetime_usd:
            raise ValueError("per-position cap above lifetime cap")
        return self

    @property
    def ledger_path(self) -> Path:
        return Path(self.ledger_dir) / f"opt-ledger-{self.mode}.jsonl"


def load_option_config(path: Path = Path("options.yaml")) -> OptionConfig:
    return OptionConfig(**(yaml.safe_load(Path(path).read_text()) or {}))
