"""방법 1. 제2의 베트남 찾기 (유사국 매칭).

1) 과거에 한국 비스킷 수출이 '이륙'한 나라와 그 직전 연도를 고정 규칙으로 찾는다.
2) 이륙 직전 그 나라들의 모습을 지표 10개로 잰다. 시대가 달라 값을 직접 비교할 수 없으므로,
   지표마다 그해 나라들 사이 백분위(0~100)로 바꾼다.
3) 지금(now_year) 각 후보의 백분위와 '이륙 직전 평균 모습'의 차이를 재서 가장 가까운 나라를 고른다.
   닮음 점수 = 100 - 평균 차이(지표 평균, 백분위 포인트).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import avg_last, ext, pct, trade, wb


def takeoffs(cfg: dict) -> list[dict]:
    a = cfg["methods"]["analog"]["takeoff"]
    kor = trade("KOR_X", cfg["hs"]).fillna(0) / 1e6
    out = []
    for c in kor.index:
        for t in range(a["first_year"], a["last_year"] + 1):
            t2 = t + a["after_years"]
            if t not in kor.columns or t2 not in kor.columns:
                continue
            s, e = kor.at[c, t], kor.at[c, t2]
            if s < a["start_below_musd"] and e >= a["end_at_least_musd"] and e >= a["multiple_at_least"] * max(s, 0.05):
                out.append({"iso3": c, "year": t, "start_musd": round(s, 2), "end_musd": round(e, 2)})
                break
    return out


def _raw(f: dict, cfg: dict, year: int, cache: dict) -> pd.Series:
    """지표 원값(그해, 나라별)."""
    hs = cfg["hs"]
    if "wb" in f:
        w = cache.setdefault(f["wb"], wb(f["wb"]))
    elif f.get("trade") in ("M", "KOR_X"):
        w = cache.setdefault(f["trade"], trade(f["trade"], hs))
    elif f.get("trade") == "KOR_SHARE":
        m = cache.setdefault("M", trade("M", hs))
        k = cache.setdefault("KOR_X", trade("KOR_X", hs)).reindex(m.index).fillna(0)
        w = k / m.replace(0, np.nan) * 100
    else:
        w = cache.setdefault(f["ext"], ext(f["ext"]))
        if f.get("per_capita"):
            pop = cache.setdefault("SP.POP.TOTL", wb("SP.POP.TOTL"))
            w = w.reindex(pop.index) / pop * 1e6
    if w.empty:
        return pd.Series(dtype=float)
    if f.get("cagr"):
        y0 = year - f["cagr"]
        if y0 not in w.columns or year not in w.columns:
            return pd.Series(dtype=float)
        return ((w[year] / w[y0]) ** (1 / f["cagr"]) - 1) * 100
    if year not in w.columns:
        return pd.Series(dtype=float)
    return w[year]


def profile(cfg: dict, year: int, pool: list[str], cache: dict, feats: list[dict] | None = None) -> pd.DataFrame:
    """pool 나라들의 그해 백분위 표(나라 × 지표)."""
    feats = feats or cfg["methods"]["analog"]["features"]
    cols = {}
    for f in feats:
        r = _raw(f, cfg, year, cache).reindex(pool).replace([np.inf, -np.inf], np.nan)
        cols[f["id"]] = pct(r).reindex(pool)
    return pd.DataFrame(cols)


def run(cfg: dict, cand: list[str], universe: list[str]) -> dict:
    feats = cfg["methods"]["analog"]["features"]
    cache: dict = {}
    cases = takeoffs(cfg)
    case_rows = []
    for k in cases:
        P = profile(cfg, k["year"], universe, cache)
        if k["iso3"] in P.index:
            row = P.loc[k["iso3"]]
            case_rows.append(row.rename(f"{k['iso3']}{k['year']}"))
    C = pd.DataFrame(case_rows)
    center = C.mean()                       # 이륙 직전 평균 모습
    now = profile(cfg, cfg["now_year"], universe, cache)
    # 최신 연도 값이 없는 지표는 1년 전으로 채움
    prev = profile(cfg, cfg["now_year"] - 1, universe, cache)
    now = now.fillna(prev)
    diff = (now.loc[[c for c in cand if c in now.index]] - center).abs()
    have = diff.notna().sum(axis=1)
    score = (100 - diff.mean(axis=1)).where(have >= len(feats) * 0.6)
    # 사례별 거리(가장 닮은 사례)
    nearest = {}
    for c in score.dropna().index:
        d = {(n): float((now.loc[c] - C.loc[n]).abs().mean()) for n in C.index}
        nearest[c] = min(d, key=d.get)
    ranked = score.dropna().sort_values(ascending=False)
    return {
        "method": "analog",
        "cases": cases,
        "case_profile": {n: {k: (None if pd.isna(v) else round(float(v), 1)) for k, v in C.loc[n].items()} for n in C.index},
        "center": {k: round(float(v), 1) for k, v in center.items()},
        "features": [{"id": f["id"], "name_ko": f["name_ko"]} for f in feats],
        "ranking": [{"iso3": c, "score": round(float(s), 1), "nearest_case": nearest[c],
                     "profile": {k: (None if pd.isna(v) else round(float(v), 1)) for k, v in now.loc[c].items()},
                     "n_features": int(have[c])}
                    for c, s in ranked.items()],
    }
