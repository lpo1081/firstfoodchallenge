"""검사 1. 실패국 부검.

한국 과자 수출이 크게 떴다가 꺾인 나라(정점 뒤 4년 안에 70% 이하)를 고정 규칙으로 찾고,
(실패 평균과 이륙 평균 모두 값이 있는 지표만 비교)
꺾이기 직전(정점 해) 그 나라들의 모습을 지표 12개(방법 1의 10개 + 수출 과열 속도·정치 안정)로 잰다.
지금 후보가 '이륙 직전 평균'과 '실패 직전 평균' 중 어느 쪽에 더 가까운지, 그리고 어떤 지표가 실패 쪽을 닮았는지 본다.
순위를 바꾸지 않는다. 경고 지표는 진출 조건으로 넘긴다.
"""
from __future__ import annotations

import pandas as pd

from .analog import profile, takeoffs
from .common import trade


def failures(cfg: dict) -> list[dict]:
    r = cfg["checks"]["failure"]["rule"]
    k = trade("KOR_X", cfg["hs"]).fillna(0) / 1e6
    s = k.T.rolling(2).mean().T
    out = []
    for c in s.index:
        row = s.loc[c]
        for t in range(r["first_year"], r["last_year"] + 1):
            if t + 1 not in row.index or t - 2 not in row.index:
                continue
            pk = row.loc[t]
            later = row.loc[t + 1:min(t + r["fall_within_years"], int(row.index.max()))]
            if pk >= r["peak_at_least_musd"] and pk >= row.loc[t - 2:t].max() and later.min() <= r["fall_to_at_most"] * pk:
                out.append({"iso3": c, "year": t, "peak_musd": round(float(pk), 1), "low_musd": round(float(later.min()), 1)})
                break
    return out


def run(cfg: dict, cand: list[str], universe: list[str], focus: list[str]) -> dict:
    fc = cfg["checks"]["failure"]
    feats = cfg["methods"]["analog"]["features"] + fc["extra_features"]
    cache: dict = {}
    fails, ups = failures(cfg), takeoffs(cfg)

    def center(cases):
        rows = []
        for x in cases:
            P = profile(cfg, x["year"], universe, cache, feats)
            if x["iso3"] in P.index:
                rows.append(P.loc[x["iso3"]].rename(f"{x['iso3']}{x['year']}"))
        return pd.DataFrame(rows)

    F, U = center(fails), center(ups)
    fc_, uc_ = F.mean(), U.mean()
    common = [f for f in fc_.index if pd.notna(fc_[f]) and pd.notna(uc_[f])]   # 두 평균 모두 값이 있는 지표만 비교
    fc_, uc_ = fc_[common], uc_[common]
    now = profile(cfg, cfg["now_year"], universe, cache, feats).fillna(profile(cfg, cfg["now_year"] - 1, universe, cache, feats))[common]
    names = {f["id"]: f["name_ko"] for f in feats}
    disc = (fc_ - uc_).abs()
    top = list(disc.sort_values(ascending=False).index[:fc["flag_top_k"]])
    rows = []
    pool = [c for c in cand if c in now.index]
    for c in pool:
        p = now.loc[c]
        df, du = float((p - fc_).abs().mean()), float((p - uc_).abs().mean())
        # 경고 지표: 실패 평균과 이륙 평균이 가장 크게 다른 지표 top_k 중, 이 나라 값이 두 평균의 중간보다 실패 쪽에 있는 것
        flags = []
        for f in top:
            if pd.isna(p[f]):
                continue
            mid = (fc_[f] + uc_[f]) / 2
            if (fc_[f] > uc_[f] and p[f] > mid) or (fc_[f] < uc_[f] and p[f] < mid):
                flags.append({"id": f, "name_ko": names[f], "now": round(float(p[f]), 1),
                              "fail_avg": round(float(fc_[f]), 1), "takeoff_avg": round(float(uc_[f]), 1)})
        rows.append({"iso3": c, "dist_fail": round(df, 1), "dist_takeoff": round(du, 1),
                     "closer_to": "실패" if df < du else "이륙", "flags": flags})
    rank_fail = sorted(rows, key=lambda r: r["dist_fail"])
    pos = {r["iso3"]: i + 1 for i, r in enumerate(rank_fail)}
    for r in rows:
        r["fail_similarity_rank"] = pos[r["iso3"]]
    return {
        "check": "failure",
        "failure_cases": fails,
        "takeoff_cases": ups,
        "fail_center": {k: round(float(v), 1) for k, v in fc_.items()},
        "takeoff_center": {k: round(float(v), 1) for k, v in uc_.items()},
        "n_candidates": len(rows),
        "biggest_differences": [{"id": f, "name_ko": names[f], "fail_avg": round(float(fc_[f]), 1), "takeoff_avg": round(float(uc_[f]), 1)}
                                for f in top],
        "focus": [r for r in rows if r["iso3"] in focus],
        "most_like_failure": rank_fail[:10],
    }
