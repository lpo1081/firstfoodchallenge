"""통합 진출국 선정 깔때기: 1 자격 심사 → 2 시장 매력도 → 3 승산 → 4 진입 비용 → 5 위험·충격 → TOP3.

규칙·비중·충격은 전부 config/funnel/protocol.yaml(결과 전 고정). 이 파일은 그 규칙을 그대로 실행만 한다.
나라마다 '몇 단계에서, 무슨 이유로' 떨어졌는지 기록한다.
"""
from __future__ import annotations

import copy
import math

import numpy as np
import pandas as pd
import yaml

from ..config import ROOT
from ..entry_cost import model as ec

FILL_MIN = {"korea_visitors_pc"}   # 방한객 통계(KTO)에 따로 안 잡히는 나라 = 방한객이 적은 나라 → 최솟값 처리
LOWER_BETTER = {"distance_km", "japan_share"}


def load_protocol(path=None):
    p = path or ROOT / "config" / "funnel" / "protocol.yaml"
    return yaml.safe_load(open(p, encoding="utf-8"))


def load_checklist():
    return yaml.safe_load(open(ROOT / "config" / "funnel" / "checklist.yaml", encoding="utf-8"))


# ------------------------------------------------------------------ 공통: 백분위 점수
def pct_scores(T: pd.DataFrame, pool: list[str], groups: dict) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    """pool 안에서 지표별 백분위(0~100) → 그룹 점수 → 단계 점수. 결측은 50점(중립), FILL_MIN 은 최하점."""
    ind = [i for g in groups.values() for i in g["indicators"]]
    raw = T.reindex(pool)[ind].copy()
    P = pd.DataFrame(index=raw.index)
    for i in ind:
        s = raw[i]
        if i in FILL_MIN:
            s = s.fillna(s.min() if s.notna().any() else 0)
        d = -1 if i in LOWER_BETTER else 1
        P[i] = (s * d).rank(pct=True) * 100
        P[i] = P[i].fillna(50.0)
    G = pd.DataFrame({g: sum(P[i] * w for i, w in spec["indicators"].items()) / sum(spec["indicators"].values())
                      for g, spec in groups.items()}, index=P.index)
    total = sum(G[g] * spec["weight"] for g, spec in groups.items()) / sum(s["weight"] for s in groups.values())
    return total, G, P


def top_share(score: pd.Series, share: float) -> list[str]:
    n = math.ceil(len(score) * share)
    return list(score.sort_values(ascending=False).index[:n])


# ------------------------------------------------------------------ 1단계
def stage1(T, cty, proto, log=print):
    u = proto["universe"]
    pool = [c for c in T.index if c in cty.index and c not in u["exclude_iso3"]
            and (T.at[c, "population"] or 0) >= u["min_population"]
            and (not u.get("need_import_data") or pd.notna(T.at[c, "import_usd"]))]
    out, reasons = [], {}
    kor_rank = T.reindex(pool)["korea_exports_usd"].sort_values(ascending=False)
    for r in proto["stage1"]["rules"]:
        if r["kind"] == "hard_filter":
            hf = yaml.safe_load(open(ROOT / r["file"], encoding="utf-8"))
            hit = {c for rr in hf["rules"] if rr["id"] in r["rule_ids"] for c in rr.get("iso3", [])}
        elif r["kind"] == "below":
            v = T.reindex(pool)[r["indicator"]]
            hit = set(v[v < r["threshold"]].index)
            if r["indicator"] == "political_stability":
                hit |= set()  # 결측은 탈락시키지 않음(미확인)
        elif r["kind"] == "entries":
            ent = yaml.safe_load(open(ROOT / r["file"], encoding="utf-8"))
            hit = {e["iso3"] for e in (ent.get("entries") or ent.get("countries") or [])}
        elif r["kind"] == "top_korea_exports":
            hit = set(kor_rank.index[: r["n"]])
        else:
            raise ValueError(r["kind"])
        r["_hit"] = hit
    for c in pool:
        why = [r["name_ko"] for r in proto["stage1"]["rules"] if c in r["_hit"]]
        if why:
            reasons[c] = why
        else:
            out.append(c)
    return pool, out, reasons


# ------------------------------------------------------------------ 4단계 비용 항목(costs.yaml + 규칙)
def cost_table(T, cty, proto, isos):
    P, C = ec.load()
    C = copy.deepcopy(C)
    fb = proto["stage4"]["fallback_costs"]
    oic = set(yaml.safe_load(open(ROOT / "config" / "funnel" / "checklist.yaml", encoding="utf-8"))["oic_members"])
    known = C["countries"]
    xp = ROOT / "config" / "funnel" / "costs_extra.yaml"
    extra = (yaml.safe_load(open(xp, encoding="utf-8")) or {}).get("countries", {}) if xp.exists() else {}
    # 국가위험 프리미엄: 확인된 Damodaran 값을 정치안정 지수에 직선으로 맞춤
    xs = [T.at[k, "political_stability"] for k in known if k in T.index and pd.notna(T.at[k, "political_stability"])]
    ys = [known[k]["crp"] for k in known if k in T.index and pd.notna(T.at[k, "political_stability"])]
    slope, icpt = np.polyfit(xs, ys, 1) if len(xs) >= 2 else (0.0, 0.02)
    grade = {}
    for c in isos:
        if c in known:
            grade[c] = "확인(costs.yaml)"
            continue
        halal = bool(fb["halal_if_oic"] and c in oic)
        fta = T.at[c, "fta_years"] > 0 if c in T.index else False
        pv = T.at[c, "political_stability"] if c in T.index else np.nan
        known[c] = {
            "name": cty.at[c, "name"] if c in cty.index else c,
            "tariff_mfn": fb["tariff_mfn"],
            "tariff_korea": fb["tariff_korea_if_fta"] if fta else fb["tariff_mfn"],
            "kcci_route": fb["route_by_region"].get(cty.at[c, "region"] if c in cty.index else "", 3508),
            "extra_language": bool(fb["extra_language_if_not_english"] and not (c in cty.index and cty.at[c, "english"])),
            "registration_per_sku": fb["registration_per_sku"],
            "halal_required": halal, "halal_one_time": fb["halal_one_time"] if halal else 0.0,
            "annual_fixed": fb["annual_fixed"] + (fb["annual_fixed_halal_extra"] if halal else 0.0),
            "prep_months": fb["prep_months"] + (fb["prep_months_halal_extra"] if halal else 0),
            "crp": float(np.clip(icpt + slope * (pv if pd.notna(pv) else -0.5), 0, 0.08)),
        }
        grade[c] = "규칙(사람 확인 필요)"
        ov = extra.get(c)
        if ov:
            known[c].update(ov)
            grade[c] = "일부 확인(costs_extra.yaml)" + (", 관세는 규칙" if "tariff_korea" not in ov else "")
    return P, C, grade, {"crp_slope": float(slope), "crp_intercept": float(icpt)}


def benefit_row(T, c):
    r = T.loc[c]
    return {"iso3": c, "kor": float(r.korea_exports_usd),
            "raw": {"import_market_size": float(r.import_market_size), "import_market_cagr": float(r.import_cagr if pd.notna(r.import_cagr) else 0.0),
                    "korea_share_change": float(r.korea_share_change if pd.notna(r.korea_share_change) else 0.0)}}


def economics(T, P, C, isos, opt=None, rev_mult=None):
    """나라별 5년 손익(entry_cost.evaluate). rev_mult: 나라별 매출 배수(충격)."""
    b = P["benefit"]
    out = {}
    for c in isos:
        lo, hi, mkt, pp1 = ec.benefit_eok(benefit_row(T, c), b)
        tgt = ec.pick(lo, hi, b["point"]) * ((rev_mult or {}).get(c, 1.0))
        r = ec.evaluate(c, tgt, P, C, opt)
        r.update({"target_range": [lo, hi], "import_market_eok": mkt})
        out[c] = r
    return out


# ------------------------------------------------------------------ 깔때기 한 번 실행
def run_funnel(T, cty, proto, s1, P, C, econ, w=None):
    """s1 = (pool, survivors, reasons). w = 비중 덮어쓰기(몬테카를로·충격). → dict"""
    w = w or {}
    g2 = w.get("stage2", proto["stage2"]["groups"])
    g3 = w.get("stage3", proto["stage3"]["groups"])
    fw = w.get("final", proto["stage5"]["final_weights"])
    _, surv, _ = s1
    a, aG, aP = pct_scores(T, surv, g2)
    s2 = top_share(a, proto["stage2"]["pass_top_share"])
    b, bG, bP = pct_scores(T, surv, g3)
    s3 = top_share(b.reindex(s2), proto["stage3"]["pass_top_share"])
    rule = proto["stage4"]["pass_if"]
    s4 = [c for c in s3 if econ[c]["npv5"] > rule["npv5_gt"]
          and econ[c]["payback_years"] is not None and econ[c]["payback_years"] <= rule["payback_years_le"]]
    risk = proto["stage5"]["risk"]
    rk = pd.DataFrame({k: (T.reindex(surv)[k] * v["direction"]).rank(pct=True) * 100 for k, v in risk.items()}).fillna(50.0)
    safety = sum(rk[k] * v["weight"] for k, v in risk.items()) / sum(v["weight"] for v in risk.values())
    bc = pd.Series({c: econ[c]["bc_ratio"] or 0 for c in s3})
    eco = bc.rank(pct=True) * 100
    final = pd.Series({c: fw["attractiveness"] * a[c] + fw["ability"] * b[c] + fw["economics"] * eco[c] + fw["safety"] * safety[c]
                       for c in s4}, dtype=float).sort_values(ascending=False)
    return {"attr": a, "attrG": aG, "attrP": aP, "abil": b, "abilG": bG, "abilP": bP, "s2": s2, "s3": s3, "s4": s4,
            "safety": safety, "safetyP": rk, "eco": eco, "final": final}


def perturb(groups, rng, k):
    out = {}
    names = list(groups)
    gw = rng.dirichlet(np.array([groups[g]["weight"] for g in names]) * k)
    for g, x in zip(names, gw):
        ids = list(groups[g]["indicators"])
        iw = rng.dirichlet(np.array([groups[g]["indicators"][i] for i in ids]) * k)
        out[g] = dict(groups[g], weight=float(x), indicators=dict(zip(ids, map(float, iw))))
    return out


def run_all(T, cty, proto, log=print):
    s1 = stage1(T, cty, proto, log)
    pool, surv, reasons = s1
    P, C, grade, crp_fit = cost_table(T, cty, proto, surv)
    econ = economics(T, P, C, surv)
    base = run_funnel(T, cty, proto, s1, P, C, econ)
    st5 = proto["stage5"]

    # ---- 충격: 4단계 진입국(s3) 각각의 5년 순이익을 다시 계산 + 충격마다 깔때기 전체 재실행 → TOP3
    shocks, npv_shock, top3_shock = {}, {}, {}
    def shock_econ(sh):
        if sh["kind"] == "cost_opt":
            return economics(T, P, C, surv, opt=sh["opt"])
        if sh["kind"] == "revenue":
            col = sh["source"]
            if col == "worst_import_drop_3y":
                m = {c: 1 + min(0.0, float(T.at[c, col]) if pd.notna(T.at[c, col]) else 0.0) / 100 for c in surv}
            else:
                m = {c: 1 / (1 + (float(T.at[c, col]) if pd.notna(T.at[c, col]) else 0.0) / 100) for c in surv}
            return economics(T, P, C, surv, rev_mult=m), m
        raise ValueError(sh["kind"])
    by_id = {s["id"]: s for s in st5["shocks"]}
    for sh in st5["shocks"]:
        if sh["kind"] == "reweight":
            g3 = copy.deepcopy(proto["stage3"]["groups"])
            for g in sh["zero_groups"]:
                g3[g]["weight"] = 0.0
            r = run_funnel(T, cty, proto, s1, P, C, econ, {"stage3": g3})
            e = econ
        elif sh["kind"] == "compound":
            opt, mult = {}, {c: 1.0 for c in surv}
            for sid in sh["of"]:
                s = by_id[sid]
                if s["kind"] == "cost_opt":
                    opt.update(s["opt"])
                else:
                    _, m = shock_econ(s)
                    mult = {c: mult[c] * m[c] for c in surv}
            e = economics(T, P, C, surv, opt=opt, rev_mult=mult)
            r = run_funnel(T, cty, proto, s1, P, C, e)
        else:
            res = shock_econ(sh)
            e = res[0] if isinstance(res, tuple) else res
            r = run_funnel(T, cty, proto, s1, P, C, e)
        npv_shock[sh["id"]] = {c: e[c]["npv5"] for c in base["s3"]}
        top3_shock[sh["id"]] = list(r["final"].index[:3])
        shocks[sh["id"]] = sh["name_ko"]

    # ---- 스트레스 규칙 → 최종 TOP3
    rule = st5["stress_rule"]
    single = [s["id"] for s in st5["shocks"] if s["kind"] in ("cost_opt", "revenue")]
    neg = {c: [s for s in single if npv_shock[s][c] <= 0] for c in base["s3"]}
    excluded = {c for c in base["s4"] if len(neg[c]) >= rule["exclude_if_negative_in_single_shocks"]}
    conditional = {c: neg[c] for c in base["s4"] if c not in excluded and len(neg[c]) >= rule["conditional_if_negative_in_single_shocks"]}
    final = base["final"].drop(list(excluded), errors="ignore")
    top = list(final.index[: proto["final"]["n"]])

    # ---- 몬테카를로: 비중을 흔들어 깔때기 전체 재실행
    mc = st5["monte_carlo"]
    rng = np.random.default_rng(mc["seed"])
    cnt, first = pd.Series(0, index=surv, dtype=float), pd.Series(0, index=surv, dtype=float)
    same3 = 0
    fw0 = st5["final_weights"]
    for _ in range(mc["draws"]):
        k = mc["dirichlet_concentration"]
        fwv = rng.dirichlet(np.array(list(fw0.values())) * k)
        r = run_funnel(T, cty, proto, s1, P, C, econ, {"stage2": perturb(proto["stage2"]["groups"], rng, k),
                                                         "stage3": perturb(proto["stage3"]["groups"], rng, k),
                                                         "final": dict(zip(fw0, fwv))})
        f = r["final"].drop(list(excluded), errors="ignore")
        t3 = list(f.index[:3])
        cnt[t3] += 1
        if t3:
            first[t3[0]] += 1
        same3 += set(t3) == set(top)
    keep = (cnt / mc["draws"] * 100).sort_values(ascending=False)

    # ---- 나라별 탈락 단계·이유
    fate = {}
    for c in pool:
        if c in reasons:
            fate[c] = {"stage": 1, "why": " · ".join(reasons[c])}
        elif c not in base["s2"]:
            fate[c] = {"stage": 2, "why": f"시장 매력도 {base['attr'][c]:.0f}점, 상위 절반 밖"}
        elif c not in base["s3"]:
            fate[c] = {"stage": 3, "why": f"승산 {base['abil'][c]:.0f}점, 매력도 통과국 중 상위 절반 밖"}
        elif c not in base["s4"]:
            e = econ[c]
            pb = "회수 못 함" if e["payback_years"] is None else f"회수 {e['payback_years']:.1f}년"
            fate[c] = {"stage": 4, "why": f"5년 순이익 {e['npv5']:.1f}억원, {pb}"}
        elif c in excluded:
            fate[c] = {"stage": 5, "why": "충격 " + ", ".join(shocks[s] for s in neg[c]) + "에서 순이익 마이너스"}
        elif c in top:
            fate[c] = {"stage": 6, "why": "최종 TOP3" + (" (조건부: " + ", ".join(shocks[s] for s in conditional[c]) + " 대비)" if c in conditional else "")}
        else:
            fate[c] = {"stage": 5, "why": f"최종 점수 {final[c]:.1f}, {list(final.index).index(c) + 1}위"}
    return {"pool": pool, "s1": surv, "reasons": reasons, "base": base, "econ": econ, "grade": grade, "crp_fit": crp_fit,
            "npv_shock": npv_shock, "top3_shock": top3_shock, "shocks": shocks, "neg": neg, "excluded": sorted(excluded),
            "conditional": conditional, "final": final, "top": top, "mc_keep": keep, "mc_first": first / mc["draws"] * 100,
            "mc_same3": same3 / mc["draws"] * 100, "fate": fate, "P": P, "C": C}
