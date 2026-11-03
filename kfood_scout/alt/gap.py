"""방법 2. 수출 갭 (기대치 대비 미실현).

무역 중력모형: 한국 비스킷 수출액 = f(상대국 비스킷 수입시장 규모, 서울과의 거리, 한국과 FTA, 1인당 소득).
모든 나라(수출 0인 나라 포함)로 한 번에 추정하고(포아송 의사최우도, PPML: 무역 중력모형 표준 추정법),
그 식이 말하는 '이 나라라면 정상적으로 팔려야 할 금액'에서 실제 수출을 뺀 것이 갭이다.
갭이 큰 나라 = 조건은 갖췄는데 아직 덜 팔고 있는 나라. 국제무역센터(ITC) 수출 잠재력 지도와 같은 계열의 생각이다.
한류·검색 같은 문화 신호는 일부러 넣지 않는다(기존 모델과 독립된 근거가 되도록).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .common import avg_last, geo, trade, wb

SEOUL = (37.5665, 126.9780)


def km(lat1, lng1, lat2, lng2) -> float:
    r = math.radians
    a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def ppml(X: np.ndarray, y: np.ndarray, iters: int = 100) -> np.ndarray:
    """포아송 의사최우도(반복 재가중 최소제곱). X 에 상수항 포함."""
    beta = np.zeros(X.shape[1])
    beta[0] = math.log(max(y.mean(), 1e-9))
    for _ in range(iters):
        mu = np.exp(X @ beta)
        z = X @ beta + (y - mu) / mu
        W = mu
        new = np.linalg.solve(X.T @ (W[:, None] * X), X.T @ (W * z))
        if np.max(np.abs(new - beta)) < 1e-8:
            beta = new
            break
        beta = new
    return beta


def design(cfg: dict, universe: list[str]) -> pd.DataFrame:
    g = cfg["methods"]["gap"]
    y, n = cfg["now_year"], cfg["smooth_years"]
    m = avg_last(trade("M", cfg["hs"]), y, n)
    kor = avg_last(trade("KOR_X", cfg["hs"]), y, n)
    gdp = avg_last(wb("NY.GDP.PCAP.PP.KD"), y, 3)
    cen = geo()
    rows = []
    for c in universe:
        if c not in cen.index or pd.isna(m.get(c)) or m.get(c, 0) <= 0 or pd.isna(gdp.get(c)):
            continue
        fta_year = g["fta_in_force"].get(c)
        rows.append({"iso3": c, "kor_x": float(kor.get(c, 0) if not pd.isna(kor.get(c, 0)) else 0),
                     "import_size": float(m[c]), "distance_km": km(*SEOUL, cen.at[c, "lat"], cen.at[c, "lng"]),
                     "fta": 1.0 if fta_year and fta_year < y else 0.0, "gdp_pc": float(gdp[c])})
    d = pd.DataFrame(rows).set_index("iso3")
    d["log_import_size"] = np.log(d.import_size)
    d["log_distance"] = np.log(d.distance_km)
    d["log_gdp_pc"] = np.log(d.gdp_pc)
    return d


def run(cfg: dict, cand: list[str], universe: list[str]) -> dict:
    g = cfg["methods"]["gap"]
    d = design(cfg, universe)
    regs = g["regressors"]
    X = np.column_stack([np.ones(len(d))] + [d[r].values for r in regs])
    beta = ppml(X, d.kor_x.values)
    d["expected"] = np.exp(X @ beta)
    d["gap"] = d.expected - d.kor_x
    d["ratio"] = d.kor_x / d.expected
    # 설명력: 실제와 기대치의 상관(제곱)
    r2 = float(np.corrcoef(d.kor_x, d.expected)[0, 1] ** 2)
    pool = d.loc[[c for c in cand if c in d.index]]
    pool = pool[pool.expected >= g["min_expected_musd"] * 1e6]
    ranked = pool.sort_values("gap", ascending=False)
    return {
        "method": "gap",
        "coef": {k: round(float(b), 3) for k, b in zip(["const"] + regs, beta)},
        "fit_r2": round(r2, 3),
        "n_countries": int(len(d)),
        "ranking": [{"iso3": c, "expected_musd": round(r.expected / 1e6, 2), "actual_musd": round(r.kor_x / 1e6, 2),
                     "gap_musd": round(r.gap / 1e6, 2), "actual_vs_expected_pct": round(r.ratio * 100, 0),
                     "fta": int(r.fta), "distance_km": round(r.distance_km), "import_size_musd": round(r.import_size / 1e6, 1)}
                    for c, r in ranked.iterrows()],
    }
