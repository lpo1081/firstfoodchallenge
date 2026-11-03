"""가설 검증기: '이 지표를 넣으면 3년 뒤 한국 수출 증가를 더 잘 맞히는가'를 표본 밖에서 판정한다.

1) 창을 1년 간격으로 겹쳐 만든다(기본 2012~2021, 각 창 = t 시점 지표 → t~t+h 실제 수출 증가).
2) 창마다 기준 모델(base)과 가설 모델(base+후보 지표)의 가중치를 각각 역산한다(rolling.fit).
3) 표본 밖 예측력: t 창에서 찾은 가중치로 t+h 창(정답 기간이 겹치지 않는 창)을 맞힌 순위상관.
4) 부트스트랩: 시험 창의 국가를 다시 뽑아 '가설 모델이 더 낫다'는 결과가 몇 %에서 유지되는지.
5) 편상관: 소득·시장 규모를 통제해도 후보 지표가 수출 증가를 설명하는지(경제 성장 효과와 분리).
6) 중복: 기존 지표와 순위상관이 높으면(>0.7) '이미 있는 정보'로 표시.
7) 개별 효과: 후보가 여러 개면 하나씩 넣은 모델도 같은 방식으로 검증.
판정 기준은 DEFAULT_RULES, 근거 문장은 사람이 읽을 한국어로 남긴다.
"""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from .. import rolling
from ..config import Indicator, criterion_from_dict
from ..indicators import compute_indicator

DEFAULT_RULES = {"accept_delta": 0.02, "accept_p": 0.80, "weak_p": 0.60}
CONTROLS = ["hh_consumption_pc_cagr", "gdp_pc_ppp", "import_market_size"]


def augment(base_raw: dict, indicators: list[dict]) -> dict:
    raw = copy.deepcopy(base_raw)
    have = {i["id"] for i in raw["indicators"]}
    keys = set(Indicator.__dataclass_fields__)
    raw["indicators"] += [{k: v for k, v in dict(i, weight=i.get("weight", 0.0)).items() if k in keys}
                          for i in indicators if i["id"] not in have]
    return raw


def _windows(panel, countries, crit, category, starts, n_fit, seed):
    out = {}
    for t in starts:
        pct, y, _ = rolling.window_matrix(panel, countries, crit, category, t)
        if len(pct) < crit.extra.get("min_window_n", 15) or y.nunique() < 3:
            continue
        out[t] = {"pct": pct, "y": y}
    return out


def _fit_all(wins, n_fit, seed):
    for t, w in wins.items():
        f = rolling.fit(w["pct"].to_numpy(), w["y"].to_numpy(), n=n_fit, seed=seed)
        w["w"], w["rho_in"] = f["robust"], f["rho_robust"]


def _rank(x):
    return pd.Series(x).rank().to_numpy()


def _spearman(a, b):
    return float(np.corrcoef(_rank(a), _rank(b))[0, 1])


def partial_spearman(x: pd.Series, y: pd.Series, Z: pd.DataFrame) -> float:
    """순위 기반 편상관: x, y 각각을 통제변수 순위로 회귀한 잔차끼리의 상관."""
    R = np.column_stack([np.ones(len(x))] + [_rank(Z[c]) for c in Z.columns]) if len(Z.columns) else np.ones((len(x), 1))
    def resid(v):
        r = _rank(v)
        beta, *_ = np.linalg.lstsq(R, r, rcond=None)
        return r - R @ beta
    return float(np.corrcoef(resid(x), resid(y))[0, 1])


def _oos(wins_b, wins_a, h, B, rng):
    """(fit t → test t+h) 쌍마다 base/aug 순위상관과 부트스트랩 차이."""
    pairs, boot = [], []
    for t in sorted(wins_b):
        s = t + h
        if s not in wins_b or t not in wins_a or s not in wins_a:
            continue
        idx = wins_b[s]["pct"].index.intersection(wins_a[s]["pct"].index)
        Pb, Pa = wins_b[s]["pct"].loc[idx].to_numpy(), wins_a[s]["pct"].loc[idx].to_numpy()
        y = wins_b[s]["y"].loc[idx].to_numpy()
        sb, sa = Pb @ wins_b[t]["w"], Pa @ wins_a[t]["w"]
        rb, ra = _spearman(sb, y), _spearman(sa, y)
        d = np.empty(B)
        n = len(y)
        for b in range(B):
            k = rng.integers(0, n, n)
            d[b] = _spearman(sa[k], y[k]) - _spearman(sb[k], y[k])
        pairs.append({"fit": t, "test": s, "n": int(n), "base": round(rb, 3), "aug": round(ra, 3), "delta": round(ra - rb, 3)})
        boot.append(d)
    if not pairs:
        return pairs, None
    D = np.nanmean(np.vstack(boot), axis=0)  # 부트스트랩 표본마다 쌍 평균
    return pairs, {"mean_delta": float(np.mean([p["delta"] for p in pairs])),
                   "p_better": float(np.mean(D > 0)),
                   "ci90": [float(np.percentile(D, 5)), float(np.percentile(D, 95))]}


def _decide(summary, rules):
    if summary is None:
        return "data_needed"
    if summary["mean_delta"] >= rules["accept_delta"] and summary["p_better"] >= rules["accept_p"]:
        return "accepted"
    if summary["mean_delta"] > 0 and summary["p_better"] >= rules["weak_p"]:
        return "weak"
    return "rejected"


def evaluate(panel, countries, base_raw: dict, hyp: dict, category: str, starts=tuple(range(2012, 2022)),
             n_fit=8000, B=500, seed=0, rules=None, solo=True) -> dict:
    rules = {**DEFAULT_RULES, **(rules or {}), **hyp.get("rules", {})}
    rng = np.random.default_rng(seed)
    cand = hyp["indicators"]
    cand_ids = [c["id"] for c in cand]
    base = criterion_from_dict(base_raw)
    aug = criterion_from_dict(augment(base_raw, cand))
    h = base.target.get("horizon", 3)

    # 데이터가 실제로 있는지(후보 지표가 계산되는 국가 수) 먼저 확인
    coverage, degenerate = {}, []
    for c in cand:
        ind = Indicator(**{k: v for k, v in c.items() if k in Indicator.__dataclass_fields__})
        v = compute_indicator(panel, ind, category, max(starts))
        coverage[c["id"]] = int(v.notna().sum())
        if v.dropna().nunique() < 5:  # 값이 거의 다 같으면(예: 0/100뿐) 정보가 없으니 검증 대상에서 뺀다
            coverage[c["id"]] = 0
            degenerate.append(c["id"])
    missing = [k for k, v in coverage.items() if v < 15]
    if len(missing) == len(cand):
        return {"hypothesis": hyp["id"], "category": category, "status": "data_needed", "coverage": coverage,
                "degenerate": degenerate, "reason": "후보 지표 데이터가 15개국 미만이거나 값이 퇴화(고유값 5개 미만)해 검증 불가: " + ", ".join(f"{k} {v}개국" for k, v in coverage.items())}
    if missing:  # 데이터 있는 지표만으로 먼저 검증하고, 나머지는 '데이터 필요'로 남긴다
        cand = [c for c in cand if c["id"] not in missing]
        cand_ids = [c["id"] for c in cand]
        aug = criterion_from_dict(augment(base_raw, cand))

    wb, wa = _windows(panel, countries, base, category, starts, n_fit, seed), _windows(panel, countries, aug, category, starts, n_fit, seed)
    _fit_all(wb, n_fit, seed)
    _fit_all(wa, n_fit, seed)
    pairs, summ = _oos(wb, wa, h, B, rng)

    ids = [i.id for i in aug.indicators]
    weights = {t: {c: round(float(w["w"][ids.index(c)]), 3) for c in cand_ids} for t, w in wa.items()}
    partial, redundancy = {}, {}
    ctrl = [c for c in CONTROLS if c in ids]
    for c in cand_ids:
        partial[c] = {t: round(partial_spearman(w["pct"][c], w["y"], w["pct"][ctrl]), 3) for t, w in wa.items()}
        last = wa[max(wa)]["pct"]
        cors = {o: abs(_spearman(last[c], last[o])) for o in ids if o not in cand_ids}
        top = max(cors, key=cors.get)
        redundancy[c] = {"most_similar": top, "rho": round(cors[top], 3)}

    status = _decide(summ, rules)
    res = {"hypothesis": hyp["id"], "statement": hyp.get("statement", ""), "category": category, "status": status,
           "rules": rules, "coverage": coverage, "data_needed": missing, "degenerate": degenerate, "windows": sorted(wa), "oos_pairs": pairs, "oos": summ,
           "candidate_weights": weights, "partial_corr": partial, "redundancy": redundancy}

    if solo and len(cand) > 1:  # 후보별 개별 효과
        res["solo"] = {}
        for c in cand:
            sub = evaluate(panel, countries, base_raw, {"id": f"{hyp['id']}:{c['id']}", "indicators": [c], "rules": hyp.get("rules", {})},
                           category, starts, n_fit, B, seed, rules, solo=False)
            res["solo"][c["id"]] = {k: sub.get(k) for k in ("status", "oos", "partial_corr", "redundancy")}
    res["reason"] = explain(res)
    return res


def explain(r: dict) -> str:
    """판정 근거를 사람이 읽을 문장으로."""
    if r["status"] == "data_needed":
        return r.get("reason", "데이터 부족")
    o = r["oos"]
    verdict = {"accepted": "채택", "weak": "보류(약한 개선)", "rejected": "기각"}[r["status"]]
    lines = [f"[{verdict}] 표본 밖 {len(r['oos_pairs'])}개 구간에서 순위상관이 평균 {o['mean_delta']:+.3f} 변했고, "
             f"국가를 다시 뽑아 본 부트스트랩의 {o['p_better'] * 100:.0f}%에서 기존 모델보다 나았다 "
             f"(90% 구간 {o['ci90'][0]:+.3f} ~ {o['ci90'][1]:+.3f})."]
    for c, pc in r["partial_corr"].items():
        vals = list(pc.values())
        early, late = np.mean(vals[: len(vals) // 2]), np.mean(vals[len(vals) // 2:])
        lines.append(f"{c}: 소득·시장 규모를 통제한 편상관 평균 {np.mean(vals):+.2f} (앞 시기 {early:+.2f} → 최근 {late:+.2f}); "
                     f"가중치 {list(r['candidate_weights'].values())[0].get(c, 0):.2f} → {list(r['candidate_weights'].values())[-1].get(c, 0):.2f}.")
        rd = r["redundancy"][c]
        if rd["rho"] > 0.7:
            lines.append(f"  주의: {rd['most_similar']}와 순위상관 {rd['rho']:.2f}로 정보가 겹침.")
    if r.get("degenerate"):
        lines.append(f"  값이 퇴화(거의 모든 나라가 같은 값)해 빠진 지표: {', '.join(r['degenerate'])} — 수집 방식 점검 필요")
    if r.get("data_needed"):
        lines.append(f"  데이터 미확보로 이번 검증에서 빠진 지표: {', '.join(r['data_needed'])}")
    for c, s in (r.get("solo") or {}).items():
        if s.get("oos"):
            lines.append(f"  단독 투입 {c}: {s['status']} (평균 {s['oos']['mean_delta']:+.3f}, 우위 {s['oos']['p_better'] * 100:.0f}%)")
    return "\n".join(lines)
