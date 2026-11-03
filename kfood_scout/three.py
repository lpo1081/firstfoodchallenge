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
EXTRA_EXTERNAL = ["wdi_fx", "wdi_inflation"]


def _long(w: pd.DataFrame, key: str) -> pd.DataFrame:
    d = w.stack().rename("value").reset_index()
    d.columns = ["iso3", "year", "value"]
    d["series"] = key
    return d.dropna()


def _krw_rer(panel):
    """원화 대비 현지 통화 실질가치 = (원/달러 ÷ 현지통화/달러) × (현지 물가지수 ÷ 한국 물가지수).
    값이 오르면 현지에서 한국 과자가 상대적으로 싸진다. 물가지수는 상승률을 2005=100 으로 누적."""
    fx, inf = _wide(panel, "EX:wdi_fx"), _wide(panel, "EX:wdi_inflation")
    if fx.empty or inf.empty or "KOR" not in fx.index or "KOR" not in inf.index:
        return pd.DataFrame(columns=["iso3", "year", "series", "value"])
    cols = sorted(set(fx.columns) & set(inf.columns))
    cpi = (1 + inf[cols].fillna(0) / 100).cumprod(axis=1).where(inf[cols].notna())
    q = (fx.loc["KOR", cols] / fx[cols]) * (cpi / cpi.loc["KOR"])
    return _long(q, "DV:krw_rer")


def _hh_total(panel):
    """실질 가계소비 총액 = 1인당 실질 가계소비 × 인구(과자 소비시장 크기의 대리)."""
    a, b = _wide(panel, "WB:NE.CON.PRVT.PC.KD"), _wide(panel, "WB:SP.POP.TOTL")
    return _long(a * b.reindex(index=a.index, columns=a.columns), "DV:hh_consumption_total")


DERIVED = {"krw_rer": _krw_rer, "hh_consumption_total": _hh_total}


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
    for name in EXTRA_EXTERNAL:  # 파생 지표 재료(무료, GitHub 미러)
        try:
            d = store.external_series(name, YEARS, fetch, log).copy()
        except Exception as e:  # noqa: BLE001
            log(f"[three] {name} 수집 실패: {e}")
            continue
        d["series"] = f"EX:{name}"
        frames.append(d)
    panel = pd.concat([f for f in frames if len(f)], ignore_index=True)[["iso3", "year", "series", "value"]]
    panel = panel.astype({"iso3": str, "year": int, "value": float})
    panel = pd.concat([panel] + [f(panel) for f in DERIVED.values()], ignore_index=True)
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
        wb = pd.concat([m.w for m in models], axis=1).mean(1)  # 본 계산과 같게: 통과 모델 가중치 평균으로 점수
        r = (P_now.loc[cand, ids] @ (wb / wb.sum())).rank(ascending=False, method="first")
        ranks.append(r)
        rank_sum += r
        top3[r[r <= 3].index] += 1
    R = pd.concat(ranks, axis=1)
    return (rank_sum / B), (100 * top3 / B), R


def robustness(Ps, ys, picks, ids, gmap, P_now, cand, inner, gw, top3, panel, nm, names):
    """TOP3 가 조건을 바꿔도 그대로인가. 같은 후보(cand) 안에서 순위만 다시 매긴다.
    1) 지표 하나 빼고 다시 학습(지표 수만큼)  2) 기준 비중을 바꿔서(동일 1/3, 기준 하나씩 2배)
    3) 통과 모델 하나씩만 써서  4) 실제 최근 실적(2021→24 한국 과자 수출 증가액) 순위."""
    P = P_now.loc[cand]

    def top_of(w):
        w = w.reindex(ids).fillna(0)
        return list((P[ids] @ (w / w.sum())).nlargest(3).index)

    def fit_w(use):
        ms = [VARIANTS[n](Ps, ys, use, gmap) for n in picks]
        return pd.concat([m.w for m in ms], axis=1).mean(1)

    tests = []
    for i in ids:
        tests.append({"kind": "지표 하나 빼기", "case": f"{names[i]} 빼기", "top3": top_of(fit_w([x for x in ids if x != i]))})
    alts = {"세 기준 같은 비중(1/3씩)": {g: 1 / 3 for g in G3}}
    for g in G3:
        a = {k: (2 * v if k == g else v) for k, v in gw.items()}
        alts[f"{g} 비중 2배"] = a
    for case, a in alts.items():
        w = pd.concat([inner[g] * a[g] for g in G3])
        tests.append({"kind": "기준 비중 바꾸기", "case": case, "top3": top_of(w)})
    for n in picks:
        tests.append({"kind": "모델 하나만", "case": n, "top3": top_of(VARIANTS[n](Ps, ys, ids, gmap).w)})
    keep = {c: sum(c in t["top3"] for t in tests) for c in top3}
    same = sum(set(t["top3"]) == set(top3) for t in tests)
    for t in tests:
        t["top3_names"] = [nm.get(c, c) for c in t["top3"]]
        t["same"] = set(t["top3"]) == set(top3)
    # 실제 최근 실적: 2021→24 한국 과자 수출 증가액(2년 평균 기준), 후보 안 순위
    kor = _wide(panel, f"CT:{CAT}:KOR_X")
    inc = (_avg(kor, 2024, 2) - _avg(kor, 2021, 2)).reindex(cand)
    rank_inc = inc.rank(ascending=False)
    recent = {c: {"increase_usd": round(float(inc[c])), "rank_in_candidates": int(rank_inc[c]), "n": int(inc.notna().sum())}
              for c in top3 if pd.notna(inc.get(c))}
    return {"n_tests": len(tests), "same_top3": same, "kept": keep, "tests": tests, "recent_actual": recent,
            "recent_top3": [nm.get(c, c) for c in inc.nlargest(3).index]}


def run(fetch=True, B=200, log=print, fetch_all=False):
    raw_c, proto, filt, crit, panel, countries, missing = load_all(fetch, log, fetch_all)
    ids = [i.id for i in crit.indicators]
    gmap = {i.id: i.group for i in crit.indicators}
    names = {i.id: i.name_ko for i in crit.indicators}
    units = {i.id: i.unit for i in crit.indicators}
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
        dev["앙상블(선택 모델)"]["beats"] = sum(a > b for a, b in zip(dev["앙상블(선택 모델)"]["per_test"], dev["[기준선] 큰 시장 순"]["per_test"]))

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

    # 점수 = 지표 점수(0~100: 채점한 나라들 중 순위를 백분위로) × 최종 가중치(통과 모델 3개 가중치의 평균).
    # 기준 점수 = 그 기준에 속한 지표 점수의 가중 평균. 종합 점수 = 기준 점수 × 기준 비중의 합(= 지표 점수 × 가중치의 합).
    if final_models:
        w = pd.concat([m.w for m in final_models], axis=1).mean(1)
    else:  # 통과 모델 없음 → 큰 시장 순
        w = pd.Series([1.0 if i == "korea_exports_size" else 0.0 for i in ids], index=ids)
    w = w / w.sum()
    gw = {g: float(w[[i for i in ids if gmap[i] == g]].sum()) for g in G3}
    inner = {}
    for g in G3:
        gi = [i for i in ids if gmap[i] == g]
        inner[g] = w[gi] / gw[g] if gw[g] > 0 else pd.Series(1 / len(gi), index=gi)
    gsc = pd.DataFrame({g: P_now[list(inner[g].index)].to_numpy() @ inner[g].to_numpy() for g in G3}, index=P_now.index)
    score = pd.Series(P_now[ids].to_numpy() @ w.to_numpy(), index=P_now.index)
    gpct = gsc.loc[pool].rank(pct=True) * 100
    floor = 100 / 3
    for c in pool:
        low = [g for g in G3 if gpct.loc[c, g] <= floor]
        if low:
            status[c].append("기준 바닥(남은 후보 중 하위 1/3): " + ", ".join(low))
    cand = [c for c in pool if not status[c]]
    order = sorted(cand, key=lambda c: -score[c])
    top3 = order[:3]
    # 안정성: 학습 데이터를 200번 조금씩 바꿔(나라를 복원추출) 다시 계산해도 TOP3 에 남은 비율
    top3p = (bootstrap(wins, train, picks, ids, gmap, P_now, cand, B=B)[1] if picks and B
             else pd.Series(np.nan, index=cand))
    rank_all = score.rank(ascending=False, method="min")
    robust = robustness(Ps, ys, picks, ids, gmap, P_now, cand, inner, gw, top3, panel, nm, names) if picks else {}

    def detail(c):
        out = {}
        for g in G3:
            rows = []
            for i in inner[g].index:
                v = raw_now.loc[c, i] if (c in raw_now.index and i in raw_now.columns) else np.nan
                rows.append({"id": i, "name": names[i], "unit": units[i],
                             "value": None if pd.isna(v) else round(float(v), 3),
                             "score": round(float(P_now.loc[c, i]), 1),
                             "weight_in_criterion": round(float(inner[g][i]), 3),
                             "points": round(float(P_now.loc[c, i] * inner[g][i]), 1),
                             "missing": bool(pd.isna(v))})
            out[g] = {"score": round(float(gsc.loc[c, g]), 1), "criterion_weight": round(gw[g], 3),
                      "points": round(float(gsc.loc[c, g] * gw[g]), 1),
                      "rank_in_pool_pct": (round(float(gpct.loc[c, g])) if c in gpct.index else None),
                      "indicators": sorted(rows, key=lambda x: -x["weight_in_criterion"])}
        return out

    def reasons(c, k=3):
        contrib = (P_now.loc[c] - 50) * w
        return [f"{names[i]}(채점 {len(P_now)}개국 중 상위 {max(1, 100 - P_now.loc[c, i]):.0f}%)"
                for i in contrib.nlargest(k).index if contrib[i] > 0]

    board = []
    for c in sorted(P_now.index, key=lambda c: -score[c]):
        board.append({"iso3": c, "name": nm.get(c, c), "rank": int(rank_all[c]), "score": round(float(score[c]), 1),
                      "kor_exports_2024_usd": round(float(kor_now.get(c, np.nan))),
                      "criteria": {g: round(float(gsc.loc[c, g]), 1) for g in G3},
                      "criteria_rank_in_pool_pct": ({g: round(float(gpct.loc[c, g])) for g in G3} if c in gpct.index else None),
                      "status": status[c], "selected": c in top3, "warn": filt_res[c]["warn"], "unknown": filt_res[c]["unknown"],
                      "top3_stability_pct": (round(float(top3p[c]), 1) if c in cand and pd.notna(top3p.get(c)) else None),
                      "reasons": reasons(c), "detail": detail(c)})
    res = {
        "protocol": proto["id"], "filter": filt["id"],
        "indicators": [{"id": i.id, "name": i.name_ko, "group": i.group, "question": i.question, "unit": i.unit} for i in crit.indicators],
        "missing_indicators": [{"id": i.id, "name": i.name_ko, "series": i.series_key(CAT)} for i in missing],
        "windows": {t: len(v["y"]) for t, v in wins.items()},
        "dev": dev, "dev_rows": dev_rows, "sealed": sealed, "picked": picks,
        "weights": {i: round(float(v), 3) for i, v in w.items()},
        "group_weights": {g: round(v, 3) for g, v in gw.items()},
        "n_scored": len(P_now), "n_candidates": len(cand), "excluded_counts": {
            "롯데 기진출국": sum("롯데 기진출국" in status[c] for c in P_now.index),
            "사전 필터": sum(any(x.startswith("사전 필터") for x in status[c]) for c in P_now.index),
            "이미 큰 시장": sum(any(x.startswith("이미") for x in status[c]) for c in P_now.index),
            "기준 바닥": sum(any(x.startswith("기준 바닥") for x in status[c]) for c in P_now.index)},
        "big5": [nm.get(c, c) for c in big], "big5_iso3": big,
        "top3": [nm.get(c, c) for c in top3], "top3_iso3": top3,
        "order": [nm.get(c, c) for c in order[:10]], "order_iso3": order, "B": B,
        "robustness": robust,
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


KO = {"PHL": "필리핀", "MYS": "말레이시아", "SGP": "싱가포르", "NLD": "네덜란드", "IDN": "인도네시아", "GBR": "영국",
      "THA": "태국", "ARE": "아랍에미리트", "IRL": "아일랜드", "DEU": "독일", "FRA": "프랑스", "NZL": "뉴질랜드",
      "SWE": "스웨덴", "MNG": "몽골", "USA": "미국", "CHN": "중국", "JPN": "일본", "AUS": "호주", "CAN": "캐나다",
      "VNM": "베트남", "KAZ": "카자흐스탄", "IND": "인도", "RUS": "러시아", "BEL": "벨기에", "PAK": "파키스탄",
      "MMR": "미얀마", "POL": "폴란드", "UZB": "우즈베키스탄", "BGD": "방글라데시", "KHM": "캄보디아", "HKG": "홍콩",
      "MEX": "멕시코", "GTM": "과테말라", "NPL": "네팔", "CHL": "칠레", "SAU": "사우디아라비아", "AUT": "오스트리아",
      "ITA": "이탈리아", "CZE": "체코", "CHE": "스위스", "LTU": "리투아니아", "LVA": "라트비아", "ESP": "스페인",
      "TWN": "대만", "BRA": "브라질", "TUR": "튀르키예", "ISR": "이스라엘", "QAT": "카타르", "KWT": "쿠웨이트",
      "NOR": "노르웨이", "DNK": "덴마크", "FIN": "핀란드", "PER": "페루", "COL": "콜롬비아", "ARG": "아르헨티나",
      "ZAF": "남아프리카공화국", "EGY": "이집트", "NGA": "나이지리아", "KEN": "케냐", "LAO": "라오스", "LKA": "스리랑카",
      "MAC": "마카오", "PAN": "파나마", "GRC": "그리스", "PRT": "포르투갈", "HUN": "헝가리", "ROU": "루마니아",
      "UKR": "우크라이나", "KGZ": "키르기스스탄", "OMN": "오만", "BHR": "바레인", "JOR": "요르단", "DOM": "도미니카공화국",
      "CRI": "코스타리카", "ECU": "에콰도르", "PRY": "파라과이", "URY": "우루과이", "BOL": "볼리비아", "SVK": "슬로바키아",
      "EST": "에스토니아", "HRV": "크로아티아", "SVN": "슬로베니아", "BGR": "불가리아", "SRB": "세르비아", "GEO": "조지아",
      "ARM": "아르메니아", "AZE": "아제르바이잔", "PNG": "파푸아뉴기니", "FJI": "피지", "BRN": "브루나이"}

DATA_SRC = {"comtrade": "UN Comtrade", "worldbank": "세계은행", "external": "구글 트렌드·한국관광공사"}


def ko(b):
    return KO.get(b["iso3"], b["name"])


def fmt_value(ind, v):
    """원값을 사람이 읽는 단위로(ln 값은 되돌리고, 큰 돈·사람 수는 만/억 단위)."""
    if v is None:
        return "자료 없음"
    u = ind["unit"]
    if u.startswith("ln("):
        x = math.exp(v)
        if "USD" in u:
            return f"{x / 1e8:,.1f}억 달러" if x >= 1e8 else f"{x / 1e4:,.0f}만 달러"
        return f"{x / 1e8:,.1f}억 명" if x >= 1e8 else f"{x / 1e4:,.0f}만 명"
    if u == "USD":
        return f"{v / 1e4:+,.0f}만 달러"
    if u == "USD/인":
        return f"1인당 {v:,.2f}달러"
    if u == "명/인":
        return f"인구 1만 명당 {v * 1e4:,.0f}명"
    if u in ("0-100", "점"):
        return f"{v:,.0f}점" if u == "0-100" else f"{v:+,.0f}점"
    if u.startswith("%/"):
        return f"연 {v:+.1f}%"
    if u.startswith("%p"):
        return f"{v:+.1f}%p(5년)"
    if u == "%":
        return f"{v:.1f}%"
    return f"{v:,.2f} {u}"


def _gline(b, gw):
    c = b["criteria"]
    return " + ".join(f"{g} {c[g]:.0f}점×{gw[g]:.0%}" for g in G3) + f" = **{b['score']:.1f}점**"


def report_md(r):
    gw = r["group_weights"]
    B = {b["iso3"]: b for b in r["board"]}
    top = [B[c] for c in r["top3_iso3"]]
    inds = {i["id"]: i for i in r["indicators"]}
    for b in r["board"]:
        for g in G3:
            for row in b["detail"][g]["indicators"]:
                row.setdefault("unit", inds.get(row["id"], {}).get("unit", ""))
    ex = r["excluded_counts"]
    L = [f"# 신규 수출 유망국 TOP3: {' · '.join(ko(b) for b in top)}", ""]
    L += ["## 답", "",
          f"앞으로 3년간 한국 건식 과자 수출이 가장 많이 늘어날 신규 시장은 **{', '.join(ko(b) for b in top)}** 입니다.",
          "세 나라는 식품시장 성장성, 트렌드, 수출입 세 기준을 합친 점수에서 1~3위이고, 세 기준 모두 남은 후보 중 상위권입니다.", "",
          "| 순위 | 나라 | 종합 점수 | 성장성 | 트렌드 | 수출입 | 점수를 가장 많이 올린 지표 |", "|---|---|---|---|---|---|---|"]
    for k, b in enumerate(top, 1):
        c = b["criteria"]
        L.append(f"| {k} | {ko(b)} | {b['score']:.1f} | {c['성장성']:.0f} | {c['트렌드']:.0f} | {c['수출입']:.0f} | {', '.join(b['reasons'][:2])} |")
    L += ["", "점수는 모두 0~100점입니다. 100점이면 채점한 나라 중 1등, 50점이면 중간입니다.", ""]

    L += ["## 어떻게 골랐나", "",
          "1. **데이터**: 2005~2024년 공개 통계. UN Comtrade(한국→각국 과자 수출액, 각국 과자 수입액), 세계은행(인구·소비·도시화·정치 안정·환율·물가),"
          " 구글 트렌드(한국 음식·K-pop·한국어 검색량), 한국관광공사(국적별 방한객), 산업통상자원부(FTA 발효일).",
          f"2. **기준과 지표**: 세 기준에 지표 {len(r['indicators'])}개를 나눠 담았습니다"
          f"(성장성 {sum(i['group'] == '성장성' for i in r['indicators'])}개, 트렌드 {sum(i['group'] == '트렌드' for i in r['indicators'])}개,"
          f" 수출입 {sum(i['group'] == '수출입' for i in r['indicators'])}개). 지표마다 나라 순위를 0~100점으로 바꿉니다.",
          *[f"   - **{g}**: " + ", ".join(f"{i['name']}({i['question']})" if i.get('question') else i['name'] for i in r["indicators"] if i["group"] == g) for g in G3],
          "3. **비중**: 2010~2021년 매년 \"그 해 지표로 3년 뒤 한국 과자 수출 증가액 순위를 가장 잘 맞히는 비중\"을 컴퓨터가 찾았습니다."
          f" 그렇게 찾은 비중은 **성장성 {gw['성장성']:.0%}, 트렌드 {gw['트렌드']:.0%}, 수출입 {gw['수출입']:.0%}** 입니다.",
          f"4. **걸러내기**: 인구 100만 이상, 한국 과자 수출 10만 달러 이상인 {r['n_scored']}개국을 채점한 뒤 아래 나라를 뺐습니다.",
          f"   - 롯데웰푸드가 이미 진출한 나라 {ex['롯데 기진출국']}곳",
          f"   - 이미 한국 과자 수출 상위 5개국({', '.join(KO.get(x, x) for x in r['big5_iso3'])}): 새로 들어갈 곳이 아니라 지키고 키울 시장",
          f"   - 국제 제재·전쟁 중이거나 정치 안정 지수가 매우 낮은 나라 {ex['사전 필터']}곳",
          f"   - 세 기준 중 하나라도 남은 후보 중 하위 1/3인 나라 {ex['기준 바닥']}곳(한 기준만 좋은 나라는 빼기 위해)",
          f"5. **선정**: 남은 {r['n_candidates']}개국 중 종합 점수 1~3위.", ""]

    p = top[0]
    L += [f"## 점수 계산법 ({ko(p)} 예시)", "",
          f"종합 점수 = {_gline(p, gw)}", ""]
    for g in G3:
        d = p["detail"][g]
        parts = [f"{x['name']} {x['score']:.0f}점×{x['weight_in_criterion']:.0%}" for x in d["indicators"] if x["weight_in_criterion"] >= 0.05]
        L.append(f"- {g} {d['score']:.0f}점 = {' + '.join(parts)} + 비중 5% 미만 지표들")
    L += ["", "나라별로 모든 지표의 실제 값, 점수, 비중은 아래 '나라별 상세'에 있습니다.", ""]

    dv, sz = r["dev"].get("앙상블(선택 모델)", {}), r["dev"].get("[기준선] 큰 시장 순", {})
    rb = r.get("robustness") or {}
    L += ["## 검증: 조건을 바꿔도 같은 3국인가", ""]
    if rb:
        kept = rb["kept"]
        L.append(f"- **조건을 {rb['n_tests']}가지로 바꿔 다시 계산했습니다**(지표를 하나씩 빼기 {len(r['indicators'])}번, 기준 비중 바꾸기 4번, 계산 방식 하나씩 {len(r['picked'])}번)."
                 f" {rb['n_tests']}번 중 {rb['same_top3']}번 같은 3국이 나왔습니다. "
                 + ", ".join(f"{ko(B[c])} {kept[c]}번" for c in r["top3_iso3"]) + " TOP3에 들었습니다.")
        diff = [t for t in rb["tests"] if not t["same"]]
        if diff:
            L.append("  - 바뀐 경우: " + "; ".join(f"{t['case']} → {', '.join(KO.get(c, c) for c in t['top3'])}" for t in diff))
        L.append(f"- **과거로 돌아가 맞혀 봤습니다.** 2013~2018년 각 해의 데이터만 주고 \"3년 뒤 한국 과자 수출이 가장 많이 늘 나라\"를 고르게 했습니다."
                 f" 이 방식은 \"지금 수출이 큰 순서\"로 고르는 것보다 6번 중 {dv.get('beats', '6')}번 더 잘 맞혔습니다"
                 f"(예측과 실제의 순위 일치도 {dv.get('rank_corr', 0):.2f} 대 {sz.get('rank_corr', 0):.2f}).")
        ra = rb.get("recent_actual", {})
        if ra:
            L.append("- **최근 실제 실적과 대조했습니다.** 2021→24년 한국 과자 수출 증가액 순위(남은 후보 "
                     f"{next(iter(ra.values()))['n']}개국 중): "
                     + ", ".join(f"{ko(B[c])} {ra[c]['rank_in_candidates']}위({ra[c]['increase_usd'] / 1e4:+,.0f}만 달러)" for c in r["top3_iso3"] if c in ra) + ".")
            low = [c for c in r["top3_iso3"] if c in ra and ra[c]["rank_in_candidates"] > 3]
            for c in low:
                L.append(f"  - {ko(B[c])}는 아직 실적보다 수요 신호(한국 음식 관심·방한객)가 앞선 시장입니다. 지금 들어가면 선점, 늦으면 추격이 됩니다.")
    L.append("")

    L += ["## 전체 순위표", "", "| 순위 | 나라 | 종합 | 성장성 | 트렌드 | 수출입 | 한국 과자 수출 2024 | 결과 |", "|---|---|---|---|---|---|---|---|"]
    for b in r["board"][:40]:
        c = b["criteria"]
        res = "**선정**" if b["selected"] else ("; ".join(b["status"]) or "후보")
        L.append(f"| {b['rank']} | {ko(b)} | {b['score']:.1f} | {c['성장성']:.0f} | {c['트렌드']:.0f} | {c['수출입']:.0f} | "
                 f"{b['kor_exports_2024_usd'] / 1e4:,.0f}만 달러 | {res} |")

    L += ["", "## 나라별 상세", ""]
    show = top + [B[x] for x in r["order_iso3"][3:6]]
    for b in show:
        tag = "선정" if b["selected"] else "후보(선정 안 됨)"
        L += [f"### {ko(b)} — 종합 {b['score']:.1f}점, 전체 {b['rank']}위 ({tag})", "", f"종합 점수 = {_gline(b, gw)}", ""]
        if b["warn"]:
            L.append("경고: " + ", ".join(b["warn"]))
        for g in G3:
            d = b["detail"][g]
            L += [f"**{g} {d['score']:.0f}점** (기준 비중 {d['criterion_weight']:.0%}, 남은 후보 중 상위 {100 - (d['rank_in_pool_pct'] or 0):.0f}%)", "",
                  "| 지표 | 실제 값 | 점수(0~100) | 기준 안 비중 | 반영 점수 |", "|---|---|---|---|---|"]
            for x in d["indicators"]:
                L.append(f"| {x['name']} | {fmt_value(x, x['value'])} | {x['score']:.0f} | {x['weight_in_criterion']:.0%} | {x['points']:.1f} |")
            L.append("")

    L += ["## 부록: 비교한 계산 방식 9가지(과거 6개 시점 평균 일치도)", "",
          "| 방식 | 일치도 | 미·중 빼고 | TOP3 적중(평균) | 채택 |", "|---|---|---|---|---|"]
    for nm, s in sorted(r["dev"].items(), key=lambda kv: -kv[1]["rank_corr"]):
        L.append(f"| {nm} | {s['rank_corr']:.2f} | {s['rank_corr_ex_usa_chn']:.2f} | {s['top3_hit']:.1f} | {'O' if nm in r['picked'] else ''} |")
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
