from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


@dataclass
class Indicator:
    id: str
    name_ko: str
    source: str
    transform: str
    window: int = 1
    direction: int = 1
    weight: float = 0.0
    series: str | None = None
    flow: str | None = None
    unit: str = ""
    meaning: str = ""
    group: str = ""
    smooth: int = 1   # cagr/diff 시작·끝 값을 몇 년 평균으로 잡을지 (이상값 완화)

    def series_key(self, category: str) -> str:
        if self.source == "comtrade":
            return f"CT:{category}:{self.flow}"
        if self.source == "external":   # 국가×연도 표 원천(sources/external.py 레지스트리)
            return f"EX:{self.series}"
        return f"WB:{self.series}"


@dataclass
class Criterion:
    id: str
    name_ko: str
    universe: dict
    indicators: list[Indicator]
    candidates: list[Indicator] = field(default_factory=list)
    target: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)   # benchmarks, min_window_n 등 메서드별 설정(키 추가 시 코드 수정 불필요)

    @property
    def weights(self) -> dict[str, float]:
        return {i.id: i.weight for i in self.indicators}

    def all_indicators(self) -> list[Indicator]:
        return self.indicators + self.candidates


def load_categories() -> dict:
    return yaml.safe_load((CONFIG / "categories.yaml").read_text())


CORE_KEYS = {"id", "name_ko", "universe", "indicators", "candidates", "target"}


def criterion_from_dict(raw: dict) -> Criterion:
    return Criterion(
        id=raw["id"], name_ko=raw["name_ko"], universe=raw["universe"],
        indicators=[Indicator(**i) for i in raw["indicators"]],
        candidates=[Indicator(**i) for i in raw.get("candidates", [])],
        target=raw.get("target", {}),
        extra={k: v for k, v in raw.items() if k not in CORE_KEYS},
    )


def load_yaml(*parts: str) -> dict:
    return yaml.safe_load(CONFIG.joinpath(*parts).read_text())


def load_criterion_raw(name: str) -> dict:
    return load_yaml("criteria", f"{name}.yaml")


def load_criterion(name: str) -> Criterion:
    return criterion_from_dict(load_criterion_raw(name))


def load_entries(name: str = "lotte_wellfood") -> dict:
    return load_yaml("entries", f"{name}.yaml")


def load_study(name: str) -> dict:
    return load_yaml("studies", f"{name}.yaml")


def load_portfolio(name: str) -> dict:
    return load_yaml("portfolios", f"{name}.yaml")
