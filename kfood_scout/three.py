"""3대 기준(식품시장 성장성 · 트렌드 · 수출입)으로 신규 유망국 TOP3 를 확정한다. 2026-11-03.

순서(검증 규칙은 config/validation/three_criteria_protocol.yaml 에 결과 보기 전 고정):
1) 창(t→t+3)마다 지표 백분위(P)와 정답(한국 과자 수출 증가액 y)을 만든다. 2010~2021, 최대 12개 창.
2) 여러 모델(VARIANTS)을 '전진 시험'으로 겨룬다. s→s+3 을 맞힐 때는 정답이 s년까지 끝난 창만으로 학습.
   개발 시험 6개(2013~2018)로만 모델을 고르고, 2021→24 봉인 시험은 보고만 한다.
3) 통과 모델 상위 3개의 순위 평균(앙상블)으로 2024년 지표에 점수를 매기고, 나라를 다시 뽑아(재표본) TOP3 확률을 센다.
4) 사전 필터(제재·전쟁·정치 불안) → 기진출국·이미 큰 시장 제외 → 세 기준 바닥 제외 → 정확히 3개국.

실행(API 비용 0원, 세계은행 무료 API만):
  .venv/bin/python -m kfood_scout.three              # 사전 필터용 세계은행 WGI(정치 안정·법치·부패)만 받고, 나머지는 저장분
  .venv/bin/python -m kfood_scout.three --no-fetch   # 저장된 데이터만
결과: outputs/three_criteria/result.json, report.md
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np
import pandas as pd
import yaml

from . import store
from .config import CONFIG, ROOT, criterion_from_dict, load_categories, load_entries, load_yaml
from .indicators import _avg, _wide, compute_all
from .rolling import spearman_many, target

CAT = "dry_confectionery"
YEARS = list(range(2005, 2025))  # 저장소에 받아 둔 연도와 같게(다시 받지 않도록)
H = 3


# ---------------------------------------------------------------- 데이터
def load_all(fetch=True, log=print, fetch_all=False):
    raw = load_yaml("criteria", "three_criteria.yaml")
    proto = load_yaml("validation", "three_criteria_protocol.yaml")
    filt = load_yaml("filters", "hard_filter.yaml")
    crit = criterion_from_dict(raw)
    cats = load_categories()
    # 무역·세계은행 기본 지표는 저장된 것만 쓴다(Comtrade 호출 0). 새로 받는 것은 사전 필터용 WGI 뿐.
    panel = store.assemble_panel(CAT, {CAT: cats[CAT]}, crit, YEARS, fetch=fetch_all, log=log)
    wgi = sorted({s for r in filt["rules"] if r["kind"] == "wgi"
                  for s in (r["series"] if isinstance(r["series"], list) else [r["series"]])})
    frames = [panel]
    for code in wgi:
        try:
            d = store.wb_series(code, YEARS, fetch, log).copy()
        except Exception as e:  # noqa: BLE001  네트워크가 막혀도 나머지는 계산
            log(f"[three] {code} 수집 실패: {e}")
            continue
        d["series"] = f"WB:{code}"
        frames.append(d)
    panel = pd.concat([f for f in frames if len(f)], ignore_index=True)[["iso3", "year", "series", "value"]]
    panel = panel.astype({"iso3": str, "year": int, "value": float})
    have = set(panel.series.unique())
    missing = [i for i in crit.indicators if i.series_key(CAT) not in have]
    crit.indicators = [i for i in crit.indicators if i.series_key(CAT) in have]
    return raw, proto, filt, crit, panel, store.countries(False), missing


def _universe(panel, countries, crit, year, base):
    u = crit.universe
    pop = _wide(panel, "WB:SP.POP.TOTL")
    popt = pop[year] if year in pop.columns else pop.ffill(axis=1).iloc[:, -1]
    ok = pd.Index(countries.iso3).difference(u.get("exclude_iso3", []))
    return [c for c in ok if popt.get(c, 0) >= u.get("min_population", 0) and base.get(c, 0) >= u.get("min_korea_exports_usd", 0)]


def _pct(raw, crit, ok):
    raw = raw.reindex(ok)
    need = math.ceil(crit.universe.get("min_indicator_share", 0.6) * len(crit.indicators))
    raw = raw[raw.notna().sum(axis=1) >= need]
    pct = pd.DataFrame({i.id: (raw[i.id] * i.direction).rank(pct=True) * 100 for i in crit.indicators},
                       index=raw.index).fillna(50.0)
    return pct, raw


def windows(panel, countries, crit, first, last):
    out = {}
    for t in range(first, last + 1):
        y, base = target(panel, CAT, crit, t)
        ok = [c for c in _universe(panel, countries, crit, t, base) if pd.notna(y.get(c))]
        pct, raw = _pct(compute_all(panel, crit.indicators, CAT, t), crit, ok)
        if len(pct) >= crit.extra.get("min_window_n", 15) and y.loc[pct.index].nunique() >= 3:
            out[t] = {"P": pct, "y": y.loc[pct.index], "raw": raw}
    return out


def now_matrix(panel, countries, crit, year):
    kor = _wide(panel, f"CT:{CAT}:KOR_X")
    base = _avg(kor[[c for c in kor.columns if c <= year]], year, 2)
    pct, raw = _pct(compute_all(panel, crit.indicators, CAT, year), crit, _universe(panel, countries, crit, year, base))
    return pct, raw, base


# ---------------------------------------------------------------- 모델(시뮬레이션 후보)
def _rho(Ps, ys, W):
    """여러 창에서 순위상관 평균. W: K×M 가중치 후보 → M개 점수."""
    return np.mean([spearman_many(P @ W, y) for P, y in zip(Ps, ys)], axis=0)


def _simplex(k, step):
    n = int(round(1 / step))
    pts = [c for c in np.ndindex(*(n + 1,) * (k - 1)) if sum(c) <= n]
    return np.array([[*c, n - sum(c)] for c in pts], float).T / n  # k×M


def _dirichlet(k, n, seed):
    rng = np.random.default_rng(seed)
    W = np.vstack([rng.dirichlet(np.full(k, a), n // 3) for a in (0.3, 1.0, 3.0)] + [np.eye(k), np.full((1, k), 1 / k)])
    return W.T


def _robust(W, r, top=0.05):
    idx = np.argsort(-r)[: max(5, int(len(r) * top))]
    return W[:, idx].mean(1)


class Model:
    """학습 결과: 지표별 가중치 w(합 1)와 기준(그룹)별 가중치."""

    def __init__(self, ids, groups, inner, gw):
        self.ids, self.groups, self.inner, self.gw = ids, groups, inner, gw  # inner: 그룹 → {지표: 가중}

    @property
    def w(self):
        out = pd.Series(0.0, index=self.ids)
        for g, a in self.gw.items():
            for i, v in self.inner.get(g, {}).items():
                out[i] += a * v
        return out / out.sum() if out.sum() > 0 else out

    def score(self, P):
        return pd.Series(P[self.ids].to_numpy() @ self.w.to_numpy(), index=P.index)

    def group_scores(self, P):
        return pd.DataFrame({g: P[list(d)].to_numpy() @ np.array(list(d.values())) for g, d in self.inner.items() if d},
                            index=P.index)


def _inner(Ps, ys, cols, how, seed):
    if not cols:
        return {}
    if how == "equal":
        return {c: 1 / len(cols) for c in cols}
    r1 = {c: float(np.mean([spearman_many(P[[c]].to_numpy(), y.to_numpy())[0] for P, y in zip(Ps, ys)])) for c in cols}
    if how == "screen":  # 학습 구간에서 정답과 같은 방향인 지표만, 같은 비중
        keep = [c for c in cols if r1[c] > 0] or [max(cols, key=r1.get)]
        return {c: 1 / len(keep) for c in keep}
    W = _dirichlet(len(cols), 2400, seed)  # fit
    w = _robust(W, _rho([P[cols].to_numpy() for P in Ps], [y.to_numpy() for y in ys], W), 0.02)
    return {c: float(v) for c, v in zip(cols, w)}


def make_variant(inner_how, groups_used, group_how="fit"):
    def fit(Ps, ys, ids, gmap, seed=0):
        inner = {g: _inner(Ps, ys, [i for i in ids if gmap[i] == g], inner_how, seed) for g in groups_used}
        inner = {g: d for g, d in inner.items() if d}
        gs = list(inner)
        if len(gs) == 1 or group_how == "equal":
            gw = {g: 1 / len(gs) for g in gs}
        else:
            G = [np.column_stack([P[list(inner[g])].to_numpy() @ np.array(list(inner[g].values())) for g in gs]) for P in Ps]
            W = _simplex(len(gs), 0.05)
            gw = dict(zip(gs, _robust(W, _rho(G, [y.to_numpy() for y in ys], W))))
        return Model(ids, gmap, inner, gw)
    return fit


def flat_fit(Ps, ys, ids, gmap, seed=0):
    W = _dirichlet(len(ids), 6000, seed)
    w = _robust(W, _rho([P[ids].to_numpy() for P in Ps], [y.to_numpy() for y in ys], W), 0.01)
    return Model(ids, gmap, {"전체": dict(zip(ids, map(float, w)))}, {"전체": 1.0})


G3 = ["성장성", "트렌드", "수출입"]
VARIANTS = {
    "3기준_동일비중": make_variant("equal", G3, "equal"),
    "3기준_기준비중학습": make_variant("equal", G3),
    "3기준_지표선별+기준비중학습": make_variant("screen", G3),
    "3기준_지표·기준비중 모두학습": make_variant("fit", G3),
    "지표 전체 한 번에 학습(기존 방식)": flat_fit,
    "성장성만": make_variant("screen", ["성장성"]),
    "트렌드만": make_variant("screen", ["트렌드"]),
    "수출입만": make_variant("screen", ["수출입"]),
    "성장성+트렌드(수출입 없이)": make_variant("screen", ["성장성", "트렌드"]),
}


# ---------------------------------------------------------------- 검증
def _metrics(pred, y, ex=("USA", "CHN")):
    act = y.rank(ascending=False)
    keep = [c for c in y.index if c not in ex]
    out = {"rank_corr": float(pred.rank().corr(y.rank())),
           "rank_corr_ex_usa_chn": float(pred[keep].rank().corr(y[keep].rank())),
           "n": len(y)}
    for k in (3, 10):
        out[f"top{k}_hit"] = len(set(pred.nlargest(k).index) & set(y.nlargest(k).index))
    out["top3"] = list(pred.nlargest(3).index)
    out["top3_actual_rank"] = [int(act[c]) for c in out["top3"]]
    return out


def walk_forward(wins, ids, gmap, tests):
    """s→s+3 시험마다 t ≤ s-3 창으로 학습. 모델·기준선 성적."""
    rows = []
    for s in tests:
        if s not in wins:
            continue
        tr = [t for t in wins if t + H <= s]
        if not tr:
            continue
        Ps, ys = [wins[t]["P"] for t in tr], [wins[t]["y"] for t in tr]
        P, y = wins[s]["P"], wins[s]["y"]
        rec = {"test": s, "train": tr, "n": len(y), "models": {}}
        for name, fit in VARIANTS.items():
            m = fit(Ps, ys, ids, gmap)
            rec["models"][name] = _metrics(m.score(P), y)
        rec["models"]["[기준선] 큰 시장 순"] = _metrics(P["korea_exports_size"] + 1e-6 * P.mean(1), y)
        prev = wins.get(s - H)
        trend = prev["y"].reindex(P.index) if prev else P.get("korea_exports_change")
        rec["models"]["[기준선] 직전 3년 증가 순"] = _metrics(trend.fillna(trend.min()), y)
        rec["random_top3"] = round(9 / len(y), 2)
        rows.append(rec)
    return rows


def summarize(rows):
    names = list(rows[0]["models"]) if rows else []
    out = {}
    for nm in names:
        ms = [r["models"][nm] for r in rows]
        out[nm] = {k: round(float(np.mean([m[k] for m in ms])), 3)
                   for k in ("rank_corr", "rank_corr_ex_usa_chn", "top3_hit", "top10_hit")}
        out[nm]["per_test"] = [round(m["rank_corr"], 3) for m in ms]
    return out


def select(dev, proto):
    size = dev["[기준선] 큰 시장 순"]
    passed = []
    for nm, s in dev.items():
        if nm.startswith("["):
            continue
        wins_vs = sum(a >= b for a, b in zip(s["per_test"], size["per_test"]))
        s["beats_size_tests"] = f"{wins_vs}/{len(size['per_test'])}"
        s["pass"] = bool(s["rank_corr"] > size["rank_corr"] and wins_vs >= math.ceil(len(size["per_test"]) * 4 / 6))
        if s["pass"]:
            passed.append(nm)
    passed.sort(key=lambda n: -dev[n]["rank_corr"])
    return passed[:3]


# ---------------------------------------------------------------- 사전 필터
def hard_filter(filt, panel, iso_list, year=2024):
    res = {c: {"exclude": [], "warn": [], "unknown": []} for c in iso_list}
    for r in filt["rules"]:
        if r["kind"] == "list":
            for c in iso_list:
                if c in r["iso3"]:
                    res[c][r["action"]].append(r["name_ko"])
            continue
        codes = r["series"] if isinstance(r["series"], list) else [r["series"]]
        for code in codes:
            w = _wide(panel, f"WB:{code}")
            if w.empty:
                for c in iso_list:
                    res[c]["unknown"].append(f"{r['name_ko']}({code} 미수집)")
                continue
            w = w[[y for y in w.columns if y <= year]]
            v = w[sorted(w.columns)[-r.get("years", 3):]].mean(axis=1)
            for c in iso_list:
                x = v.get(c, np.nan)
                if pd.isna(x):
                    res[c]["unknown"].append(f"{r['name_ko']}({code} 값 없음)")
                elif "exclude_below" in r and x < r["exclude_below"]:
                    res[c]["exclude"].append(f"{r['name_ko']}({code} {x:.2f})")
                elif "warn_below" in r and x < r["warn_below"]:
                    res[c]["warn"].append(f"{r['name_ko']}({code} {x:.2f})")
    return res


# ---------------------------------------------------------------- 최종 전망
def ensemble_rank(models, P):
    return pd.concat([m.score(P).rank(ascending=False) for m in models], axis=1).mean(1)


def bootstrap(wins, train, picks, ids, gmap, P_now, cand, B=200, seed=0):
    rng = np.random.default_rng(seed)
    rank_sum = pd.Series(0.0, index=cand)
    top3 = pd.Series(0, index=cand)
    pair = {}
    ranks = []
    for b in range(B):
        Ps, ys = [], []
        for t in train:
            idx = rng.integers(0, len(wins[t]["y"]), len(wins[t]["y"]))
            Ps.append(wins[t]["P"].iloc[idx]); ys.append(wins[t]["y"].iloc[idx])
        models = [VARIANTS[n](Ps, ys, ids, gmap, seed=b) for n in picks]
        r = ensemble_rank(models, P_now.loc[cand]).rank(method="first")
        ranks.append(r)
        rank_sum += r
        top3[r[r <= 3].index] += 1
    R = pd.concat(ranks, axis=1)
    return (rank_sum / B), (100 * top3 / B), R


def run(fetch=True, B=200, log=print, fetch_all=False):
    raw_c, proto, filt, crit, panel, countries, missing = load_all(fetch, log, fetch_all)
    ids = [i.id for i in crit.indicators]
    gmap = {i.id: i.group for i in crit.indicators}
    names = {i.id: i.name_ko for i in crit.indicators}
    nm = countries.set_index("iso3")["name"].to_dict()
    wcfg = proto["windows"]
    wins = windows(panel, countries, crit, wcfg["first"], wcfg["sealed_test"])
    log(f"[three] 지표 {len(ids)}개(미수집 {len(missing)}), 창 {sorted(wins)} 국가 수 {[len(w['y']) for w in wins.values()]}")

    dev_rows = walk_forward(wins, ids, gmap, wcfg["dev_tests"])
    dev = summarize(dev_rows)
    picks = select(dev, proto)
    sealed_rows = walk_forward(wins, ids, gmap, [wcfg["sealed_test"]])
    sealed = summarize(sealed_rows)
    if picks:
        # 봉인 시험: 앙상블 그대로
        s = wcfg["sealed_test"]
        tr = [t for t in wins if t + H <= s]
        ms = [VARIANTS[n]([wins[t]["P"] for t in tr], [wins[t]["y"] for t in tr], ids, gmap) for n in picks]
        sealed["앙상블(선택 모델)"] = {k: v for k, v in _metrics(-ensemble_rank(ms, wins[s]["P"]), wins[s]["y"]).items()}
        dev_ens = []
        for r in dev_rows:
            s = r["test"]
            tr = [t for t in wins if t + H <= s]
            ms = [VARIANTS[n]([wins[t]["P"] for t in tr], [wins[t]["y"] for t in tr], ids, gmap) for n in picks]
            dev_ens.append(_metrics(-ensemble_rank(ms, wins[s]["P"]), wins[s]["y"]))
        dev["앙상블(선택 모델)"] = {k: round(float(np.mean([m[k] for m in dev_ens])), 3)
                                for k in ("rank_corr", "rank_corr_ex_usa_chn", "top3_hit", "top10_hit")}
        dev["앙상블(선택 모델)"]["per_test"] = [round(m["rank_corr"], 3) for m in dev_ens]

    # 최종: 2021년 창까지 전부 학습
    fy = wcfg["forecast_year"]
    train = [t for t in wins if t + H <= fy]
    P_now, raw_now, kor_now = now_matrix(panel, countries, crit, fy)
    Ps, ys = [wins[t]["P"] for t in train], [wins[t]["y"] for t in train]
    final_models = [VARIANTS[n](Ps, ys, ids, gmap) for n in picks] if picks else []

    existing = {e["iso3"] for e in load_entries()["entries"]}
    big = list(kor_now.reindex(P_now.index).nlargest(5).index)
    filt_res = hard_filter(filt, panel, list(P_now.index), fy)
    status = {}
    for c in P_now.index:
        why = []
        if c in existing:
            why.append("롯데 기진출국")
        if filt_res[c]["exclude"]:
            why.append("사전 필터: " + ", ".join(filt_res[c]["exclude"]))
        if c in big:
            why.append("이미 한국 과자 수출 상위 5개국(지키고 키울 시장)")
        status[c] = why
    pool = [c for c in P_now.index if not status[c]]

    # 기준별 점수(후보 안 백분위)와 바닥 기준 제외
    if final_models:
        gsc = pd.concat([m.group_scores(P_now) for m in final_models]).groupby(level=0).mean()
        gsc = gsc[[g for g in G3 if g in gsc.columns]]  # 바닥 규칙은 세 기준만(기존 방식 모델의 "전체" 열 제외)
        overall_rank = ensemble_rank(final_models, P_now)
    else:  # 통과 모델 없음 → 큰 시장 순
        gsc = pd.DataFrame({g: P_now[[i for i in ids if gmap[i] == g]].mean(1) for g in G3})
        overall_rank = P_now["korea_exports_size"].rank(ascending=False)
    gpct = gsc.loc[pool].rank(pct=True) * 100
    floor = 100 / 3
    for c in pool:
        low = [g for g in gpct.columns if gpct.loc[c, g] <= floor]
        if low:
            status[c].append("기준 바닥(하위 1/3): " + ", ".join(low))
    cand = [c for c in pool if not status[c]]

    mean_rank, top3p, R = (bootstrap(wins, train, picks, ids, gmap, P_now, cand, B=B) if picks and B
                           else (overall_rank.loc[cand].rank(), pd.Series(np.nan, index=cand), None))
    order = sorted(cand, key=lambda c: (round(mean_rank[c], 6), -top3p.get(c, 0)))
    top3 = order[:3]
    third_vs_fourth = (float((R.loc[order[2]] < R.loc[order[3]]).mean() * 100)
                       if R is not None and len(order) > 3 else None)

    w = (pd.concat([m.w for m in final_models], axis=1).mean(1) if final_models else pd.Series(dtype=float))

    def reasons(c, k=3):
        if w.empty:
            return []
        contrib = (P_now.loc[c] - 50) * w
        return [f"{names[i]}(상위 {max(1, 100 - P_now.loc[c, i]):.0f}%)" for i in contrib.nlargest(k).index if contrib[i] > 0]

    board = []
    for c in sorted(P_now.index, key=lambda c: overall_rank[c]):
        board.append({"iso3": c, "name": nm.get(c, c), "overall_rank": round(float(overall_rank[c]), 1),
                      "kor_exports_2024_usd": round(float(kor_now.get(c, np.nan))),
                      "groups_pct_in_pool": ({g: round(float(gpct.loc[c, g])) for g in gpct.columns} if c in gpct.index else None),
                      "status": status[c], "warn": filt_res[c]["warn"], "unknown": filt_res[c]["unknown"],
                      "boot_mean_rank": (round(float(mean_rank[c]), 2) if c in cand else None),
                      "top3_prob": (round(float(top3p[c]), 1) if c in cand and pd.notna(top3p.get(c)) else None),
                      "reasons": reasons(c)})
    res = {
        "protocol": proto["id"], "filter": filt["id"],
        "indicators": [{"id": i.id, "name": i.name_ko, "group": i.group} for i in crit.indicators],
        "missing_indicators": [{"id": i.id, "name": i.name_ko, "series": i.series_key(CAT)} for i in missing],
        "windows": {t: len(v["y"]) for t, v in wins.items()},
        "dev": dev, "dev_rows": dev_rows, "sealed": sealed, "picked": picks,
        "weights": {i: round(float(v), 3) for i, v in w.items()},
        "group_weights": {g: round(float(w[[i for i in w.index if gmap[i] == g]].sum()), 3) for g in G3} if len(w) else {},
        "big5": [nm.get(c, c) for c in big],
        "top3": [nm.get(c, c) for c in top3], "top3_iso3": top3,
        "order": [nm.get(c, c) for c in order[:10]],
        "third_over_fourth_pct": third_vs_fourth, "B": B,
        "board": board,
    }
    d = ROOT / "outputs" / "three_criteria"
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    (d / "report.md").write_text(report_md(res))
    # 레드팀(agent critic --ranking) 입력: 최종 후보를 순위 순으로
    (d / "ranking.json").write_text(json.dumps({"ranking": [{"iso3": c, "name": nm.get(c, c)} for c in order]},
                                               ensure_ascii=False, indent=1))
    return res


def _f(x):
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else (f"{x:+.2f}" if isinstance(x, float) else str(x))


def report_md(r):
    L = [f"# 3대 기준 TOP3 결과 (검증 규칙 {r['protocol']}, 필터 {r['filter']})", ""]
    L.append(f"**신규 TOP3: {', '.join(r['top3'])}**  (재표본 {r['B']}회, 3위가 4위보다 위였던 비율 {'-' if r['third_over_fourth_pct'] is None else round(r['third_over_fourth_pct'])}%)")
    L.append("")
    L.append(f"후보 순서(1~10): {' > '.join(r['order'])}")
    L.append(f"이미 큰 시장(제외, 지키고 키울 시장): {', '.join(r['big5'])}")
    L.append("")
    L.append("## 1. 모델 겨루기(개발 시험 6개 평균, 모델 선택은 여기서만)")
    L.append("| 모델 | 순위상관 | 미·중 빼고 | TOP3 적중 | TOP10 적중 | 시험별 순위상관 | 큰 시장 순 이긴 시험 | 통과 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for nm, s in sorted(r["dev"].items(), key=lambda kv: -kv[1]["rank_corr"]):
        L.append(f"| {nm} | {s['rank_corr']:+.3f} | {s['rank_corr_ex_usa_chn']:+.3f} | {s['top3_hit']:.2f} | {s['top10_hit']:.2f} | "
                 f"{' '.join(f'{x:+.2f}' for x in s['per_test'])} | {s.get('beats_size_tests', '-')} | {'O' if s.get('pass') else ''} |")
    L.append(f"\n선택(앙상블): {', '.join(r['picked']) or '없음 → 큰 시장 순'}")
    L.append("\n## 2. 봉인 시험(2018년까지 학습 → 2021→24, 보고만)")
    L.append("| 모델 | 순위상관 | 미·중 빼고 | TOP3 적중 | TOP10 적중 |")
    L.append("|---|---|---|---|---|")
    for nm, s in sorted(r["sealed"].items(), key=lambda kv: -kv[1]["rank_corr"]):
        L.append(f"| {nm} | {s['rank_corr']:+.3f} | {s['rank_corr_ex_usa_chn']:+.3f} | {s['top3_hit']} | {s['top10_hit']} |")
    L.append("\n## 3. 기준 비중과 지표 가중치(최종 학습)")
    L.append("기준 비중: " + ", ".join(f"{g} {v:.0%}" for g, v in r["group_weights"].items()))
    names = {i["id"]: (i["name"], i["group"]) for i in r["indicators"]}
    for i, v in sorted(r["weights"].items(), key=lambda kv: -kv[1]):
        if v >= 0.005:
            L.append(f"- [{names[i][1]}] {names[i][0]}: {v:.1%}")
    if r["missing_indicators"]:
        L.append("\n미수집 지표(다음 실행 때 자동 수집): " + ", ".join(m["name"] for m in r["missing_indicators"]))
    L.append("\n## 4. 나라별 판정(종합 순위 순, 상위 30)")
    L.append("| 순위 | 나라 | 한국 수출 2024(만$) | 성장성/트렌드/수출입(후보 안 백분위) | TOP3 확률 | 판정 | 경고 | 이유(점수 올린 지표) |")
    L.append("|---|---|---|---|---|---|---|---|")
    for b in r["board"][:30]:
        g = b["groups_pct_in_pool"]
        gs = "/".join(str(g.get(x, "-")) for x in G3) if g else "-"
        st = "; ".join(b["status"]) or "후보"
        L.append(f"| {b['overall_rank']:.0f} | {b['name']} | {b['kor_exports_2024_usd'] / 1e4:,.0f} | {gs} | {_f(b['top3_prob'])} | {st} | "
                 f"{'; '.join(b['warn'] + b['unknown'][:1])} | {', '.join(b['reasons'])} |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kfood_scout.three")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--fetch-all", action="store_true", help="무역·세계은행 기본 지표도 없는 연도를 받음(보통 불필요)")
    ap.add_argument("--B", type=int, default=200)
    a = ap.parse_args(argv)
    r = run(fetch=not a.no_fetch, B=a.B, fetch_all=a.fetch_all)
    print(report_md(r)[:3000])
    print("저장:", ROOT / "outputs" / "three_criteria")


if __name__ == "__main__":
    main()
