"""지표 계산: 패널 + 지표 정의 + 기준연도(as_of) → 국가 × 지표 원값.

as_of 를 바꾸면 '그 해에 알 수 있었던 데이터'만으로 다시 계산된다(역산 검증의 핵심).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Indicator


def _wide(panel: pd.DataFrame, key: str) -> pd.DataFrame:
    s = panel[panel.series == key]
    return s.pivot_table(index="iso3", columns="year", values="value", aggfunc="sum")


def _value_near(w: pd.DataFrame, year: int, tol: int = 1, prefer: int = -1) -> pd.Series:
    """year 값, 없으면 ±tol 년 값(prefer 방향 먼저)."""
    out = w[year] if year in w.columns else pd.Series(np.nan, index=w.index)
    for d in range(1, tol + 1):
        for yy in (year + prefer * d, year - prefer * d):
            if yy in w.columns:
                out = out.fillna(w[yy])
    return out


def _avg(w: pd.DataFrame, year: int, k: int) -> pd.Series:
    """year 를 끝으로 하는 k년 평균(있는 연도만). 없으면 ±1년 값."""
    if k <= 1:
        return _value_near(w, year)
    cols = [c for c in range(year - k + 1, year + 1) if c in w.columns]
    val = w[cols].mean(axis=1) if cols else pd.Series(np.nan, index=w.index)
    return val.fillna(_value_near(w, year))


def _share(panel, category, year, k):
    kor = _wide(panel, f"CT:{category}:KOR_X")
    imp = _wide(panel, f"CT:{category}:M")
    kor = kor[[c for c in kor.columns if c <= year]]
    imp = imp[[c for c in imp.columns if c <= year]]
    a, b = _avg(kor, year, k), _avg(imp, year, k)
    a = a.reindex(b.index.union(a.index)).fillna(0.0)
    return (a / b.reindex(a.index)).where(lambda x: x.notna()) * 100


def compute_indicator(panel: pd.DataFrame, ind: Indicator, category: str, as_of: int) -> pd.Series:
    w = _wide(panel, ind.series_key(category))
    w = w[[c for c in w.columns if c <= as_of]]  # 미래 데이터 차단
    if w.empty:
        return pd.Series(dtype=float, name=ind.id)
    t = ind.transform
    if t in ("share", "share_diff"):
        val = _share(panel, category, as_of, 3)
        if t == "share_diff":
            val = val - _share(panel, category, as_of - ind.window, 3)
        return val.rename(ind.id)
    if t == "per_capita_cagr":
        pop = _wide(panel, "WB:SP.POP.TOTL")
        pc = (w / pop.reindex(index=w.index, columns=w.columns))
        end, start = _avg(pc, as_of, ind.smooth), _avg(pc, as_of - ind.window, ind.smooth)
        val = (((end / start) ** (1 / ind.window) - 1) * 100).where((end > 0) & (start > 0))
        return val.rename(ind.id)
    if t in ("level", "level_log", "per_capita"):
        cols = [c for c in range(as_of - ind.window + 1, as_of + 1) if c in w.columns]
        val = w[cols].mean(axis=1) if cols else pd.Series(np.nan, index=w.index)
        if val.isna().any():  # 최근 연도 미보고 시 1년 이전 값으로 보완
            val = val.fillna(_value_near(w, as_of - 1))
        if t == "per_capita":
            pop = _wide(panel, "WB:SP.POP.TOTL")
            val = val / _value_near(pop, as_of).reindex(val.index)
        if t == "level_log":
            val = np.log(val.where(val > 0))
    elif t in ("cagr", "diff"):
        if ind.smooth > 1:
            end, start = _avg(w, as_of, ind.smooth), _avg(w, as_of - ind.window, ind.smooth)
        else:
            end = _value_near(w, as_of, prefer=-1)
            start = _value_near(w, as_of - ind.window, prefer=+1)
        if t == "cagr":
            ok = (end > 0) & (start > 0)
            val = ((end / start) ** (1 / ind.window) - 1) * 100
            val = val.where(ok)
        else:
            val = end - start
    else:
        raise ValueError(f"unknown transform {t}")
    return val.rename(ind.id)


def compute_all(panel: pd.DataFrame, indicators: list[Indicator], category: str, as_of: int) -> pd.DataFrame:
    return pd.concat([compute_indicator(panel, i, category, as_of) for i in indicators], axis=1)
