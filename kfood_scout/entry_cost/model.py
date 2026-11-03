"""나라별 '진출 목표 매출'에서 실제 진출 비용을 빼고 국가위험으로 할인해 5년 순이익을 비교한다.

모든 숫자는 config/entry_cost/protocol.yaml(규칙)과 costs.yaml(비용 항목, 출처)에서 온다.
API 호출 없음, 비용 0원.
"""
import copy
import json
import math
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config/entry_cost"


def load(protocol=CFG / "protocol.yaml", costs=CFG / "costs.yaml"):
    return (yaml.safe_load(open(protocol, encoding="utf-8")),
            yaml.safe_load(open(costs, encoding="utf-8")))


# ---------- 편익: 진출 목표 매출 (PR #14 와 같은 공식) ----------
def benefit_eok(c, b):
    """패널의 한 나라 → 3년 뒤 연 목표 매출(억원) (low, high)."""
    r = c["raw"]
    mkt = math.exp(r["import_market_size"])
    kor = c["kor"]; share = kor / mkt; n = b["years_ahead"]
    mkt_n = mkt * (1 + r["import_market_cagr"] / 100) ** n
    trend_share = share + r["korea_share_change"] / 100 * n / 5
    inc = sorted([mkt_n * share - kor, mkt_n * trend_share - kor])
    gain = mkt_n * b["share_gain_pp"] / 100
    eok = lambda usd: usd * b["krw_per_usd"] / 1e8
    lo, hi = (eok(gain + max(x, 0) * b["lotte_share_of_korea"]) for x in inc)
    return lo, hi, eok(mkt), eok(mkt_n * 0.01)


def pick(lo, hi, point):
    return {"low": lo, "high": hi, "mid": (lo + hi) / 2}[point]


# ---------- 비용 ----------
def tariff(cc, case):
    if case == "mfn":
        return cc["tariff_mfn"]
    if cc["tariff_korea"] is not None:
        return cc["tariff_korea"]
    if case == "fta_zero":
        return 0.0
    return min(cc["tariff_mfn"], 0.05)   # 확인 못한 FTA 세율 규칙


def evaluate(iso, revenue_target, P, C, opt=None):
    """한 나라의 5년 손익. revenue_target = 연 목표 매출(억원, CIF 기준)."""
    o = {"gross_margin": P["gross_margin"], "launch_promo_rate": P["launch_promo_rate"],
         "freight_mult": 1.0, "crp_mult": 1.0, "tariff_case": "rule",
         "base_discount_rate": P["base_discount_rate"], "halal_skus_only": 1.0}
    o.update(opt or {})
    cm, cc = C["common"], C["countries"][iso]
    freight = cc["kcci_route"] / cm["feu_cargo_value_usd"] * o["freight_mult"]
    t = tariff(cc, o["tariff_case"])
    var_rate = t + cm["insurance_customs_rate"]
    sell_share = o["halal_skus_only"] if cc["halal_required"] else 1.0
    rev_full = revenue_target / (1 + freight) * sell_share     # 롯데 수출(FOB) 매출
    one_time = (cm["skus"] * (cm["label_per_sku"] + (cm["label_extra_language"] if cc["extra_language"] else 0)
                              + cc["registration_per_sku"]) + cc["halal_one_time"])
    rate = o["base_discount_rate"] + cc["crp"] * o["crp_mult"]
    ramp = list(P["ramp"])[: P["horizon_years"]]
    ramp[0] *= max(0.0, 1 - cc["prep_months"] / 12)
    rows, cum, payback = [], -one_time, None
    pv_b = pv_c = 0.0
    npv = -one_time; pv_c += one_time
    for y, k in enumerate(ramp, start=1):
        rev = rev_full * k
        gp = rev * o["gross_margin"]
        promo = rev * o["launch_promo_rate"] if y <= 2 else 0.0
        cost = rev * var_rate + promo + cc["annual_fixed"]
        profit = gp - cost
        d = (1 + rate) ** y
        npv += profit / d; pv_b += gp / d; pv_c += cost / d
        prev = cum; cum += profit
        if payback is None and cum >= 0:
            payback = y - 1 + (-prev / profit if profit > 0 else 0)
        rows.append({"year": y, "revenue": rev, "gross_profit": gp, "tariff": rev * t,
                     "other_variable": rev * cm["insurance_customs_rate"], "promo": promo,
                     "fixed": cc["annual_fixed"], "profit": profit})
    return {"iso3": iso, "name": cc["name"], "revenue_target": revenue_target, "revenue_fob": rev_full,
            "freight_rate": freight, "tariff_rate": t, "one_time": one_time, "discount_rate": rate,
            "npv5": npv, "bc_ratio": pv_b / pv_c if pv_c else None, "payback_years": payback,
            "years": rows}


def rank(res, tie_pct=0.05):
    out = sorted(res, key=lambda r: -r["npv5"])
    for i in range(len(out) - 1):     # 동률 규칙: npv 차이 5% 이내면 bc_ratio 큰 나라
        a, b = out[i], out[i + 1]
        if abs(a["npv5"] - b["npv5"]) <= tie_pct * abs(a["npv5"]) and b["bc_ratio"] > a["bc_ratio"]:
            out[i], out[i + 1] = b, a
    return out


def run(P=None, C=None, panel=None, opt=None, point=None, isos=None):
    if P is None or C is None:
        P, C = load()
    b = P["benefit"]
    if panel is None:
        panel = {c["iso3"]: c for c in json.load(open(ROOT / b["panel"]))["countries"]}
    res = []
    for iso in isos or P["candidates"]:
        lo, hi, mkt, pp1 = benefit_eok(panel[iso], b)
        r = evaluate(iso, pick(lo, hi, point or b["point"]), P, C, opt)
        r.update({"target_range": [lo, hi], "import_market_2024": mkt, "value_of_1pp": pp1})
        res.append(r)
    return rank(res, 0.05)


def sensitivity(P, C, panel):
    base = run(P, C, panel)
    first = base[0]["iso3"]
    top3_order = [r["iso3"] for r in base if r["iso3"] in P["top3"]]
    cases = []
    for key, vals in P["sensitivity"].items():
        for v in vals:
            if key == "benefit_point":
                r = run(P, C, panel, point=v)
            else:
                r = run(P, C, panel, opt={key: v})
            cases.append({"change": f"{key}={v}", "first": r[0]["iso3"],
                          "top3_order": [x["iso3"] for x in r if x["iso3"] in P["top3"]],
                          "order": [x["iso3"] for x in r]})
    return {"base_first": first, "base_top3_order": top3_order, "cases": cases,
            "first_kept": sum(c["first"] == first for c in cases),
            "top3_order_kept": sum(c["top3_order"] == top3_order for c in cases), "n": len(cases)}
