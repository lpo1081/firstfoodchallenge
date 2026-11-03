"""롤링 역산: '3년 뒤 실제로 뜬 나라'를 맞히는 프로그램 X를 시기별로 찾고, X의 변화로 현재 모델 XX를 만든다.

1) 창(window) t→t+h 마다 정답 = 한국 과자 수출 증가(실측, UN Comtrade).
2) t 시점 지표만으로 정답 순위를 가장 잘 맞히는 가중치(=X_t)를 탐색(스피어만 순위상관 최대화).
3) X_t 들을 합쳐 XX(지금 쓸 가중치)를 만든다. 합치는 방식(combine)은 기준 파일에서 고른다:
   latest(기본, 최신 X 그대로) / mean2(최근 두 X 평균) / extrapolate(추세 한 걸음 연장, 옛 방식).
   2026-11-03 검토: 추세 연장은 직전 X보다 나은 적이 없어 기본값에서 뺐다. 세 방식의 표본 밖 성적은 xx_test 에 함께 남긴다.
4) 검증: X_(t-1)이 다음 창을 얼마나 맞혔나(표본 밖 예측력), 각 합치기 방식이 마지막 창을 얼마나 맞혔나.
5) XX를 최신 데이터에 적용해 향후 h년 TOP 국가를 뽑는다.
6) TOP 확률: 마지막 창의 국가를 다시 뽑아(부트스트랩) 가중치를 다시 찾고, 각 나라가 TOP-k 에 드는 비율을 센다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import _avg, _wide, compute_all


def _rank(a: np.ndarray) -> np.ndarray:
    return a.argsort(axis=0).argsort(axis=0).astype(float)


def spearman_many(S: np.ndarray, y: np.ndarray) -> np.ndarray:
    """S: N×K 점수, y: N 정답 → K개 순위상관."""
    rs, ry = _rank(S), _rank(y[:, None])
    rs -= rs.mean(0)
    ry -= ry.mean(0)
    return (rs * ry).sum(0) / np.sqrt((rs ** 2).sum(0) * (ry ** 2).sum(0))


def target(panel, category, crit, t):
    tg = crit.target
    w = _wide(panel, f"CT:{category}:{tg.get('series', 'KOR_X')}")
    h = tg.get("horizon", 3)
    start, end = _avg(w, t, 2), _avg(w, t + h, 2)
    if tg.get("kind", "abs") == "log":
        y = np.log((end + 1e4) / (start + 1e4))
    else:
        y = end - start
    return y, start


def _min_base(u):
    """정답 시리즈의 기준연도 값 하한. 옛 이름(min_korea_exports_usd)도 그대로 받는다."""
    return u.get("min_target_base_usd", u.get("min_korea_exports_usd", 0))


def window_matrix(panel, countries, crit, category, t):
    raw = compute_all(panel, crit.indicators, category, t)
    y, base = target(panel, category, crit, t)
    u = crit.universe
    pop = _wide(panel, "WB:SP.POP.TOTL")
    popt = pop[t] if t in pop.columns else pop.iloc[:, -1]
    ok = raw.index.intersection(countries.iso3).difference(u.get("exclude_iso3", []))
    ok = [c for c in ok if popt.get(c, 0) >= u.get("min_population", 0)
          and base.get(c, 0) >= _min_base(u) and pd.notna(y.get(c))]
    raw = raw.loc[ok]
    raw = raw[raw.notna().sum(axis=1) >= u.get("min_indicator_coverage", 1)]
    pct = pd.DataFrame({i.id: (raw[i.id] * i.direction).rank(pct=True) * 100 for i in crit.indicators},
                       index=raw.index).fillna(50.0)
    return pct, y.loc[pct.index], raw


def fit(P: np.ndarray, y: np.ndarray, n=30000, seed=0, local=True):
    rng = np.random.default_rng(seed)
    k = P.shape[1]
    W = np.vstack([rng.dirichlet(np.full(k, a), n // 3) for a in (0.3, 1.0, 3.0)] + [np.eye(k), np.full((1, k), 1 / k)])
    r = spearman_many(P @ W.T, y)
    top = np.argsort(-r)[: max(20, len(W) // 100)]
    best = W[top[0]].copy()
    if not local:  # 부트스트랩 반복용: robust(상위 1% 평균)만 필요
        rob = W[top].mean(0)
        return {"best": best, "robust": rob, "rho_best": float(r[top[0]]), "rho_robust": float(spearman_many(P @ rob[:, None], y)[0])}
    # 국소 탐색으로 다듬기
    for step in (0.05, 0.02, 0.01):
        improved = True
        while improved:
            improved = False
            for i in range(k):
                for j in range(k):
                    if i == j or best[j] < step:
                        continue
                    cand = best.copy(); cand[i] += step; cand[j] -= step
                    if spearman_many(P @ cand[:, None], y)[0] > spearman_many(P @ best[:, None], y)[0] + 1e-9:
                        best, improved = cand, True
    return {"best": best, "robust": W[top].mean(0), "rho_best": float(spearman_many(P @ best[:, None], y)[0]),
            "rho_robust": float(spearman_many(P @ W[top].mean(0)[:, None], y)[0])}


def rho(pct, y, w):
    return float(spearman_many(pct.to_numpy() @ np.asarray(w)[:, None], y.to_numpy())[0])


def extrapolate(ws: list[np.ndarray]) -> np.ndarray:
    """가중치 추세를 한 창 앞으로 연장(선형), 음수 0 처리 후 합 1."""
    if len(ws) == 1:
        return ws[0]
    A = np.array(ws)
    x = np.arange(len(ws))
    slope = np.polyfit(x, A, 1)[0]
    nxt = np.clip(A[-1] + slope, 0, None)
    return nxt / nxt.sum() if nxt.sum() > 0 else A[-1]


COMBINE = {
    "latest": lambda ws: ws[-1],
    "mean2": lambda ws: np.mean(ws[-2:], axis=0),
    "extrapolate": extrapolate,
}


TIER_NAMES = {2: ["큰 시장", "작은 시장"], 3: ["큰 시장", "중간 시장", "작은 시장"]}


def tiers_of(size: pd.Series, n=3) -> pd.Series:
    """한국 수출 규모(값이 클수록 큰 시장)로 n체급. 경계는 그 시점 후보국 분위수."""
    names = TIER_NAMES.get(n, [f"{i + 1}체급" for i in range(n)])
    q = size.rank(pct=True, ascending=False)  # 0에 가까울수록 큰 시장
    return pd.Series([names[min(n - 1, int((v - 1e-9) * n))] for v in q], index=size.index)


def top_probability(pct_fit, y_fit, pct_now, B=200, ks=(3, 5, 10), n_fit=4000, seed=0):
    """마지막 창의 국가를 복원추출로 다시 뽑아 가중치를 B번 다시 찾고, 각 나라가 TOP-k 에 든 비율(%)."""
    rng = np.random.default_rng(seed)
    P, yv, N = pct_fit.to_numpy(), y_fit.to_numpy(), len(y_fit)
    now = pct_now.to_numpy()
    cnt = {k: np.zeros(len(pct_now)) for k in ks}
    for b in range(B):
        idx = rng.integers(0, N, N)
        if len(np.unique(yv[idx])) < 3:
            continue
        w = fit(P[idx], yv[idx], n=n_fit, seed=seed + b, local=False)["robust"]
        order = np.argsort(-(now @ w))
        for k in ks:
            cnt[k][order[:k]] += 1
    return {c: {f"top{k}": round(100 * cnt[k][i] / B, 1) for k in ks} for i, c in enumerate(pct_now.index)}


def run(panel, countries, crit, category, starts=(2012, 2015, 2018, 2021), forecast_year=2024, existing=(),
        combine=None, top_prob_B=None):
    ids = [i.id for i in crit.indicators]
    names = {i.id: i.name_ko for i in crit.indicators}
    groups = {i.id: i.group for i in crit.indicators}
    wins, skipped = [], []
    min_n = crit.extra.get("min_window_n", 15)
    for t in starts:
        pct, y, raw = window_matrix(panel, countries, crit, category, t)
        if len(pct) < min_n or y.nunique() < 3:
            skipped.append({"t": t, "n": len(pct)})
            continue
        f = fit(pct.to_numpy(), y.to_numpy())
        actual_top = list(y.sort_values(ascending=False).index[:10])
        wins.append({"t": t, "h": crit.target.get("horizon", 3), "n": len(pct), "pct": pct, "y": y, **f,
                     "actual_top": actual_top})
    if not wins:
        raise ValueError(f"{category}: 평가 가능한 창이 없음 (창별 국가 수 {skipped})")
    eq = np.full(len(ids), 1 / len(ids))
    bench = {"equal": eq}
    for name, ind in crit.extra.get("benchmarks", {"momentum": "korea_exports_cagr",
                                                     "size_only": "korea_exports_size"}).items():
        bench[name] = np.array([1.0 if i == ind else 0 for i in ids])
    oos = []
    for a, b in zip(wins[:-1], wins[1:]):
        oos.append({"fit": a["t"], "test": b["t"], "X_prev": rho(b["pct"], b["y"], a["robust"]),
                    **{k: rho(b["pct"], b["y"], v) for k, v in bench.items()}, "in_sample_best": b["rho_best"]})
    combine = combine or crit.extra.get("combine", "latest")
    # 합치기 방식 검증: 마지막 창 직전까지의 X 들로 만든 가중치가 마지막 창을 얼마나 맞혔나
    xx_test = None
    if len(wins) >= 3:
        prev, last = [w["robust"] for w in wins[:-1]], wins[-1]
        xx_test = {"test": last["t"], "combine": combine, "X_prev": rho(last["pct"], last["y"], prev[-1]),
                   **{f"XX_{k}": rho(last["pct"], last["y"], f(prev)) for k, f in COMBINE.items()}}
        xx_test["XX_extrapolated"] = xx_test["XX_extrapolate"]  # 옛 대시보드 호환
    XX = COMBINE[combine]([w["robust"] for w in wins])
    # 최신 데이터로 전망
    raw_now = compute_all(panel, crit.indicators, category, forecast_year)
    u = crit.universe
    pop = _wide(panel, "WB:SP.POP.TOTL")
    popn = pop.ffill(axis=1).iloc[:, -1]
    def latest(series):
        w = _wide(panel, f"CT:{category}:{series}")
        return _avg(w[[c for c in w.columns if c <= forecast_year]], forecast_year, 2) if len(w.columns) else pd.Series(dtype=float)
    korn = latest("KOR_X")                                   # 표시용: 한국 수출
    tbase = latest(crit.target.get("series", "KOR_X"))      # 거르기·체급용: 정답 시리즈(예: M = 전체 수입)
    ok = raw_now.index.intersection(countries.iso3).difference(u.get("exclude_iso3", []))
    ok = [c for c in ok if popn.get(c, 0) >= u.get("min_population", 0) and tbase.get(c, 0) >= _min_base(u)]
    raw_now = raw_now.loc[ok]
    raw_now = raw_now[raw_now.notna().sum(axis=1) >= u.get("min_indicator_coverage", 1)]
    pct_now = pd.DataFrame({i.id: (raw_now[i.id] * i.direction).rank(pct=True) * 100 for i in crit.indicators},
                           index=raw_now.index).fillna(50.0)
    nm = countries.set_index("iso3")["name"].to_dict()

    B = crit.extra.get("top_prob_B", 200) if top_prob_B is None else top_prob_B
    prob = top_probability(wins[-1]["pct"], wins[-1]["y"], pct_now, B=B) if B else {}

    ntier = crit.extra.get("tiers", 0)
    tier = tiers_of(tbase.reindex(pct_now.index).fillna(0), ntier) if ntier else pd.Series(dtype=object)

    def board(w):
        s = (pct_now @ w).sort_values(ascending=False)
        out = [{"iso3": c, "name": nm.get(c, c), "score": round(float(v), 1), "existing": c in existing,
                "kor_exports_usd": float(korn.get(c, np.nan)), "target_base_usd": float(tbase.get(c, np.nan)), **({"prob": prob[c]} if c in prob else {}),
                **({"tier": tier[c]} if c in tier else {})} for c, v in s.items()]
        seen = {}
        for r in out:  # 체급 안 순위
            if "tier" in r:
                seen[r["tier"]] = seen.get(r["tier"], 0) + 1
                r["tier_rank"] = seen[r["tier"]]
        return out

    def wdict(w):
        return {i: round(float(x), 3) for i, x in zip(ids, w)}

    def gsum(w):
        out = {}
        for i, x in zip(ids, w):
            out[groups[i]] = round(out.get(groups[i], 0) + float(x), 3)
        return out

    return {
        "indicators": [{"id": i.id, "name": names[i.id], "group": groups[i.id], "unit": i.unit} for i in crit.indicators],
        "windows": [{"t": w["t"], "h": w["h"], "n": w["n"], "weights": wdict(w["robust"]), "best_weights": wdict(w["best"]),
                     "groups": gsum(w["robust"]), "rho_best": w["rho_best"], "rho_robust": w["rho_robust"],
                     "actual_top": [nm.get(c, c) for c in w["actual_top"]]} for w in wins],
        "skipped_windows": skipped, "out_of_sample": oos, "xx_test": xx_test,
        "combine": combine, "top_prob_B": B, "tiers": TIER_NAMES.get(ntier, []) if ntier else [], "XX": wdict(XX), "XX_groups": gsum(XX), "X_latest": wdict(wins[-1]["robust"]),
        "forecast_year": forecast_year, "forecast_XX": board(XX), "forecast_X_latest": board(wins[-1]["robust"]),
        "pct_now": {c: {i: round(float(pct_now.loc[c, i]), 1) for i in ids} for c in pct_now.index},
        "raw_now": {c: {i: (None if pd.isna(raw_now.loc[c, i]) else round(float(raw_now.loc[c, i]), 3)) for i in ids}
                    for c in raw_now.index},
    }
