"""스코어링: 평가대상국(universe) 필터 → 지표별 백분위(0~100) → 가중합.

백분위 정규화를 쓰는 이유: 지표마다 단위·분포가 달라도(로그 규모, %성장률, %p) 같은 잣대로 합칠 수 있고,
극단값 한두 나라가 전체 점수를 끌고 가지 않는다.
"""
from __future__ import annotations

import pandas as pd

from .config import Criterion, Indicator
from .indicators import compute_all


def universe(raw: pd.DataFrame, panel: pd.DataFrame, countries: pd.DataFrame,
             criterion: Criterion, as_of: int) -> pd.Index:
    u = criterion.universe
    pop = panel[(panel.series == "WB:SP.POP.TOTL") & (panel.year <= as_of)]
    pop = pop.sort_values("year").groupby("iso3")["value"].last()
    ok = pop[pop >= u.get("min_population", 0)].index
    ok = ok.intersection(countries.iso3).difference(u.get("exclude_iso3", []))
    core = [i.id for i in criterion.indicators]
    cov = raw.reindex(ok)[core].notna().sum(axis=1)
    return cov[cov >= u.get("min_indicator_coverage", len(core))].index


def normalize(raw: pd.DataFrame, indicators: list[Indicator]) -> pd.DataFrame:
    out = {}
    for ind in indicators:
        col = raw[ind.id] * ind.direction
        out[ind.id] = col.rank(pct=True) * 100
    return pd.DataFrame(out, index=raw.index)


def weighted_score(pct: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    w = pd.Series(weights, dtype=float)
    w = w[w > 0]
    filled = pct[w.index].fillna(50.0)  # 결측 지표는 중립(50)으로 — 결측 플래그는 별도 표시
    return (filled * w).sum(axis=1) / w.sum()


def score(panel: pd.DataFrame, countries: pd.DataFrame, criterion: Criterion, category: str,
          as_of: int, weights: dict[str, float] | None = None, with_candidates: bool = True):
    inds = criterion.all_indicators() if with_candidates else criterion.indicators
    raw = compute_all(panel, inds, category, as_of)
    uni = universe(raw, panel, countries, criterion, as_of)
    raw = raw.reindex(uni)
    pct = normalize(raw, inds)
    s = weighted_score(pct, weights or criterion.weights)
    table = pd.DataFrame({"score": s, "rank": s.rank(ascending=False, method="min").astype(int)})
    table = table.join(countries.set_index("iso3")[["name", "region", "income"]])
    core = [i.id for i in criterion.indicators]
    na = raw[core].isna()
    table["missing"] = pd.Series([",".join(na.columns[na.loc[i]]) for i in na.index], index=na.index)
    return table.sort_values("rank"), raw, pct
