"""Risk score configuration model and loader. Weights live in risk_weights.yaml only."""
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.decision.enums import CheckStatus

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "risk_weights.yaml"


class ScoreRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: int = Field(ge=0)
    max: Optional[int] = None

    @model_validator(mode="after")
    def _check_bounds(self) -> "ScoreRange":
        if self.max is not None and self.max < self.min:
            raise ValueError("range max must be >= min")
        return self


class RiskRanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low: ScoreRange
    medium: ScoreRange
    high: ScoreRange

    @model_validator(mode="after")
    def _check_contiguous(self) -> "RiskRanges":
        if self.low.min != 0:
            raise ValueError("low range must start at 0")
        for prev, nxt, name in ((self.low, self.medium, "low/medium"), (self.medium, self.high, "medium/high")):
            if prev.max is None:
                raise ValueError(f"only the high range may be open-ended ({name})")
            if nxt.min != prev.max + 1:
                raise ValueError(f"ranges must be contiguous and non-overlapping ({name})")
        if self.high.max is not None:
            raise ValueError("high range must be open-ended (max: null)")
        return self


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: Dict[CheckStatus, int]
    resale_bonus: int = Field(ge=0)
    quantity_threshold: int = Field(ge=0)
    quantity_bonus: int = Field(ge=0)
    needs_confirmation_bonus: int = Field(ge=0)
    contradiction_forces_high: bool
    ranges: RiskRanges

    @model_validator(mode="after")
    def _check_weights(self) -> "RiskConfig":
        missing = set(CheckStatus) - set(self.weights)
        if missing:
            raise ValueError("missing weights for: " + ", ".join(sorted(s.value for s in missing)))
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("weights must be non-negative")
        return self


def parse_risk_config(data: Any) -> RiskConfig:
    return RiskConfig.model_validate(data)


def load_risk_config(path: Union[str, Path, None] = None) -> RiskConfig:
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return parse_risk_config(data)
