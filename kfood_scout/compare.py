"""study 결과 비교: 대조군(baseline) 대비 각 run 의 흐름이 같은지/다른지 + 포트폴리오 가중 통합 순위.

run 이 몇 개든, 어떤 축이든 같은 코드로 비교된다(run JSON 만 읽음).
새 비교 지표는 METRICS 또는 SIMILARITY 에 함수 하나 추가.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import ROOT, load_portfolio, load_study


def _spearman(a: pd.Series, b: pd.Series) -> float | None:
    c = a.index.intersection(b.index)
    if len(c) < 5:
        return None
    return float(a[c].rank().corr(b[c].rank()))


def _scores(res, key="forecast_XX") -> pd.Series:
    return pd.Series({c["iso3"]: c["score"] for c in res[key]})


def _cagr(ctx: dict, a: int, b: int):
    va, vb = ctx.get(str(a), ctx.get(a)), ctx.get(str(b), ctx.get(b))
    return None if not va or not vb else (vb / va) ** (1 / (b - a)) - 1


# ---------- run 단독 지표 ----------
def m_summary(res):
    w = res["windows"]
    groups = sorted({g for x in w for g in x["groups"]})
    kx = res["context"]["KOR_X"]
    ys = sorted(int(y) for y in kx)
    return {
        "n_windows": [x["n"] for x in w],
        "group_path": {g: [x["groups"].get(g, 0) for x in w] for g in groups},
        "group_trend": {g: round(w[-1]["groups"].get(g, 0) - w[0]["groups"].get(g, 0), 3) for g in groups},
        "XX_groups": res["XX_groups"],
        "fit_rho": [round(x["rho_robust"], 3) for x in w],
        "oos_X_prev": float(np.mean([o["X_prev"] for o in res["out_of_sample"]])) if res["out_of_sample"] else None,
        "oos_momentum": float(np.mean([o["momentum"] for o in res["out_of_sample"]])) if res["out_of_sample"] else None,
        "top5_new_XX": [c["name"] for c in res["forecast_XX"] if not c["existing"]][:5],
        "kor_exports_last": kx.get(str(ys[-1]), kx.get(ys[-1])) if ys else None,
        "kor_exports_cagr_10y": _cagr(kx, ys[-1] - 10, ys[-1]) if ys else None,
    }


METRICS = {"summary": m_summary}


# ---------- 대조군과의 유사도 ----------
def s_forecast_rank(a, b):
    return _spearman(_scores(a), _scores(b))


def s_top10_overlap(a, b):
    ta = [c["iso3"] for c in a["forecast_XX"] if not c["existing"]][:10]
    tb = [c["iso3"] for c in b["forecast_XX"] if not c["existing"]][:10]
    return len(set(ta) & set(tb))


def s_weight_corr(a, b):
    ka = list(a["XX"])
    return float(np.corrcoef([a["XX"][k] for k in ka], [b["XX"].get(k, 0) for k in ka])[0, 1])


def s_trend_agree(a, b):
    ga, gb = m_summary(a)["group_trend"], m_summary(b)["group_trend"]
    return {g: bool(np.sign(ga[g]) == np.sign(gb.get(g, 0))) for g in ga}


SIMILARITY = {"forecast_rank_corr": s_forecast_rank, "top10_overlap": s_top10_overlap,
              "XX_weight_corr": s_weight_corr, "group_trend_same_direction": s_trend_agree}


def consensus(results: dict, portfolio: dict, top=15, min_cover=0.5):
    """포트폴리오 매출 비중으로 카테고리별 순위 백분위를 가중평균한 통합 순위."""
    shares = portfolio["categories"]
    rows = {}
    names, existing = {}, {}
    for r in results.values():
        cat = r["combo"]["category"]
        if r.get("error") or cat not in shares:
            continue
        s = _scores(r).rank(pct=True)
        for c in r["forecast_XX"]:
            names[c["iso3"]], existing[c["iso3"]] = c["name"], c["existing"]
        for iso, p in s.items():
            rows.setdefault(iso, {})[cat] = p
    total = sum(shares[c]["share"] for c in {r["combo"]["category"] for r in results.values()} if c in shares)
    out = []
    for iso, d in rows.items():
        wsum = sum(shares[c]["share"] for c in d)
        if wsum / total < min_cover:
            continue
        out.append({"iso3": iso, "name": names[iso], "existing": existing[iso],
                    "score": round(100 * sum(shares[c]["share"] * p for c, p in d.items()) / wsum, 1),
                    "coverage": round(wsum / total, 2),
                    "by_category": {c: round(100 * p, 1) for c, p in d.items()}})
    out.sort(key=lambda x: -x["score"])
    return out


def _union_indicators(results):
    """run 마다 지표 구성이 다를 수 있으므로(기준 축) 모든 run 의 지표를 합친다."""
    seen, out = set(), []
    for r in results.values():
        for i in r.get("indicators", []) if not r.get("error") else []:
            if i["id"] not in seen:
                seen.add(i["id"]); out.append(i)
    return out


def compare(study_name: str) -> dict:
    study = load_study(study_name)
    d = ROOT / "outputs" / "studies" / study_name
    results = {p.stem: json.loads(p.read_text()) for p in sorted((d / "runs").glob("*.json"))}
    # 현재 study 의 축 값에 해당하는 run 만(축에서 뺀 값은 비교에서 빠짐)
    results = {k: v for k, v in results.items()
               if all(v["combo"].get(a) in vals for a, vals in study["axes"].items())}
    base = next((v for v in results.values() if all(v["combo"].get(k) == x for k, x in study["baseline"].items())), None)
    runs = []
    for k, r in results.items():
        row = {"run_id": k, "combo": r["combo"], "category_name": r.get("category_name"), "error": r.get("error"),
               "hs_codes": r.get("hs_codes"), "context": r.get("context")}
        if not r.get("error"):
            row.update({name: f(r) for name, f in METRICS.items()})
            row["windows"] = r["windows"]
            row["XX"] = r["XX"]
            row["forecast_XX"] = r["forecast_XX"][:40]
            if base and not base.get("error"):
                row["vs_baseline"] = {name: f(r, base) for name, f in SIMILARITY.items()}
        runs.append(row)
    out = {"study": study, "baseline_run": base["run_id"] if base else None, "runs": runs,
           "indicators": _union_indicators(results)}
    if study.get("portfolio"):
        pf = load_portfolio(study["portfolio"])
        out["portfolio"] = pf
        out["consensus"] = consensus(results, pf)
    (d / "comparison.json").write_text(json.dumps(out, ensure_ascii=False, default=float), encoding="utf-8")
    return out
