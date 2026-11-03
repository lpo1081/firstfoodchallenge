"""검사 2. 시간여행 시험.

과거 시점 T(예: 2015년)로 돌아가 T년까지의 데이터만 주고 각 방법에 TOP10을 고르게 한 뒤,
T→T+5년 실제 한국 과자 수출 증가액 TOP10과 몇 개가 겹쳤는지 센다(적중 수). 여러 T의 평균을 낸다.
비교 기준: 무작위(기대 적중 = 10×10/후보 수), 큰 시장순(T년 과자 수입시장 규모), 직전 추세(T-3→T 한국 수출 증가액).
후보·제외 규칙은 T년 기준으로 다시 계산한다(롯데 기진출국 목록만 현재 것을 씀).
"""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from . import analog, follow, gap
from .common import avg_last, candidates, rank_corr, trade

RUN = {"analog": analog.run, "gap": gap.run, "follow": follow.run}


def as_of(cfg: dict, T: int) -> dict:
    c = copy.deepcopy(cfg)
    c["now_year"] = T
    c["methods"]["analog"]["takeoff"]["last_year"] = T - c["methods"]["analog"]["takeoff"]["after_years"]
    f = c["methods"]["follow"]
    span = f["to_year"] - f["from_year"]
    f["to_year"], f["from_year"] = T, T - span
    return c


def baseline(name: str, cfg: dict, cand: list[str]) -> list[str]:
    T, n = cfg["now_year"], cfg["smooth_years"]
    if name == "big_market":
        s = avg_last(trade("M", cfg["hs"]), T, n)
    else:  # recent_trend
        k = trade("KOR_X", cfg["hs"])
        s = avg_last(k, T, n) - avg_last(k, T - 3, n).reindex(k.index).fillna(0)
    return list(s.reindex(cand).dropna().sort_values(ascending=False).index)


def run(cfg: dict) -> dict:
    tc = cfg["checks"]["timetravel"]
    H, N = tc["horizon"], tc["top_n"]
    kor = trade("KOR_X", cfg["hs"])
    names = list(RUN) + tc["baselines"]
    per = {m: [] for m in names}
    rand, years = [], []
    for T in tc["as_of"]:
        if T + H > cfg["now_year"]:
            continue
        c = as_of(cfg, T)
        cand, _, uni = candidates(c)
        actual = (avg_last(kor, T + H, c["smooth_years"]) - avg_last(kor, T, c["smooth_years"]).reindex(kor.index).fillna(0))
        actual = actual.reindex(cand).fillna(0).sort_values(ascending=False)
        truth = set(actual.index[:N])
        years.append(T)
        rand.append(N * N / len(cand))
        for m in names:
            if m in RUN:
                picks = [r["iso3"] for r in RUN[m](c, cand, uni)["ranking"]]
            else:
                picks = baseline(m, c, cand)
            top = picks[:N]
            order = pd.Series(range(len(picks)), index=picks, dtype=float)
            per[m].append({"as_of": T, "hits": len(truth & set(top)), "hit_names": sorted(truth & set(top)),
                           "rank_corr": round(rank_corr(-order, actual), 3)})
    summary = {m: {"mean_hits": round(float(np.mean([x["hits"] for x in v])), 2),
                   "mean_rank_corr": round(float(np.nanmean([x["rank_corr"] for x in v])), 3), "per_year": v}
               for m, v in per.items()}
    return {"check": "timetravel", "as_of": years, "horizon": H, "top_n": N,
            "random_hits": round(float(np.mean(rand)), 2), "methods": summary}
