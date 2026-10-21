"""Configuration: universe, risk limits and data settings, loaded from TOML."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Universe:
    book: dict[str, float]                      # ticker -> weight as a fraction of NAV
    hedges: list[str] = field(default_factory=lambda: ["TLT", "IEF"])
    market: str = "QQQ"                         # market factor proxy
    ai_factor: list[str] = field(default_factory=list)   # equal-weight basket for the AI factor
    priors: dict[str, str] = field(default_factory=dict)  # short-history name -> proxy ticker for its beta prior

    @property
    def equities(self) -> list[str]:
        return sorted(set(self.book) | set(self.hedges) | {self.market} | set(self.ai_factor))


@dataclass
class RiskParams:
    target_vol: float = 0.20            # annualized book volatility target
    max_gross: float = 1.50             # leverage cap on the equity book
    kelly_fraction: float = 0.25        # quarter Kelly: full Kelly on estimated means is reckless
    mean_prior_years: float = 10.0      # shrink sample means toward zero with a 10-year pseudo-sample
    max_drawdown: float = 0.25          # tolerated peak-to-trough loss
    drawdown_confidence: float = 0.95   # ...at this confidence over one year
    trim_band: float = 0.20             # trim a name once it runs 20% above target weight
    max_hedge_ratio: float = 1.0        # long-only hedge, at most $1 of hedge per $1 of book
    cost_bps: float = 2.0               # one-way trading cost on turnover
    financing_spread_bps: float = 100.0 # borrow cost over the cash rate on leverage
    corr_halflife: int = 63             # stock-bond correlation half-life (days)
    beta_halflife: int = 126            # factor beta half-life (days)
    min_obs: int = 60                   # observations before a beta is trusted on its own
    tail_quantile: float = 0.05         # "worst days" = worst 5% of book days


@dataclass
class DataParams:
    source: str = "synthetic"           # databento | csv | synthetic
    start: str = "2018-05-01"
    end: str | None = None
    equities_dataset: str = "auto"      # auto picks EQUS.SUMMARY if its history covers start, else XNAS.ITCH
    futures_dataset: str = "GLBX.MDP3"
    futures_roots: list[str] = field(default_factory=lambda: ["ZN", "UB"])
    csv_path: str | None = None
    cache_dir: str = ".cache"
    use_fred: bool = True
    sec_user_agent: str = "Your Name your@email.com"  # SEC requires a real contact
    risk_free_series: str = "DGS3MO"


@dataclass
class Config:
    universe: Universe
    risk: RiskParams = field(default_factory=RiskParams)
    data: DataParams = field(default_factory=DataParams)


def load_config(path: str | Path) -> Config:
    raw = tomllib.loads(Path(path).read_text())
    u = raw.get("universe", {})
    universe = Universe(
        book={k: float(v) for k, v in u.get("book", {}).items()},
        hedges=list(u.get("hedges", ["TLT", "IEF"])),
        market=u.get("market", "QQQ"),
        ai_factor=list(u.get("ai_factor", [])),
        priors=dict(u.get("priors", {})),
    )
    return Config(universe=universe, risk=RiskParams(**raw.get("risk", {})), data=DataParams(**raw.get("data", {})))


def default_config() -> Config:
    book = {"MSFT": 0.14, "AMZN": 0.14, "GOOGL": 0.14, "META": 0.12, "NVDA": 0.14,
            "AVGO": 0.08, "TSLA": 0.10, "SPCX": 0.08, "ORCL": 0.06}
    return Config(universe=Universe(book=book, ai_factor=list(book), priors={"SPCX": "TSLA"}))
