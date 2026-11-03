"""진출 비용 모듈: 가짜 나라 두 개로 계산 규칙을 확인 (원천 데이터 불필요)."""
import math

from kfood_scout.entry_cost.model import benefit_eok, evaluate, rank, run, sensitivity, tariff

P = {"gross_margin": 0.3, "launch_promo_rate": 0.1, "base_discount_rate": 0.08,
     "horizon_years": 5, "ramp": [0.33, 0.67, 1, 1, 1], "candidates": ["AAA", "BBB"], "top3": ["AAA", "BBB"],
     "benefit": {"years_ahead": 3, "krw_per_usd": 1400, "lotte_share_of_korea": 0.29,
                 "share_gain_pp": 1.0, "point": "mid"},
     "sensitivity": {"crp_mult": [0.0, 2.0], "benefit_point": ["low", "high"]}}
BASE = {"tariff_mfn": 0.1, "tariff_korea": 0.0, "kcci_route": 1000, "extra_language": False,
        "registration_per_sku": 0.0, "halal_required": False, "halal_one_time": 0.0,
        "annual_fixed": 0.0, "prep_months": 0, "crp": 0.0}
C = {"common": {"skus": 10, "label_per_sku": 0.03, "label_extra_language": 0.02,
                "insurance_customs_rate": 0.01, "feu_cargo_value_usd": 50000},
     "countries": {"AAA": dict(BASE, name="A"), "BBB": dict(BASE, name="B", crp=0.05)}}
PANEL = {iso: {"iso3": iso, "name": iso, "kor": 1e7,
               "raw": {"import_market_size": math.log(5e8), "import_market_cagr": 5.0,
                       "korea_share_change": 0.0}} for iso in ("AAA", "BBB")}


def test_tariff_rule():
    assert tariff({"tariff_mfn": 0.15, "tariff_korea": None}, "rule") == 0.05
    assert tariff({"tariff_mfn": 0.03, "tariff_korea": None}, "rule") == 0.03
    assert tariff({"tariff_mfn": 0.15, "tariff_korea": 0.0}, "rule") == 0.0
    assert tariff({"tariff_mfn": 0.15, "tariff_korea": 0.0}, "mfn") == 0.15


def test_benefit_matches_impact_formula():
    lo, hi, mkt, pp1 = benefit_eok(PANEL["AAA"], P["benefit"])
    assert lo == hi                                  # 비중 변화 0이면 범위가 한 점
    assert abs(pp1 - 5e8 * 1.05 ** 3 * 0.01 * 1400 / 1e8) < 1e-9


def test_country_risk_lowers_value():
    a = evaluate("AAA", 100, P, C); b = evaluate("BBB", 100, P, C)
    assert b["npv5"] < a["npv5"] and a["discount_rate"] == 0.08


def test_tariff_and_halal_lower_value():
    base = evaluate("AAA", 100, P, C)
    assert evaluate("AAA", 100, P, C, {"tariff_case": "mfn"})["npv5"] < base["npv5"]
    C2 = {"common": C["common"], "countries": {"AAA": dict(BASE, name="A", halal_required=True, halal_one_time=0.5)}}
    h = evaluate("AAA", 100, P, C2, {"halal_skus_only": 0.6})
    assert h["one_time"] > base["one_time"] and h["npv5"] < base["npv5"]


def test_rank_and_sensitivity():
    r = run(P, C, PANEL)
    assert [x["iso3"] for x in r] == ["AAA", "BBB"]
    s = sensitivity(P, C, PANEL)
    assert s["n"] == 4 and s["base_first"] == "AAA"


def test_tie_rule_prefers_bc_ratio():
    a = {"iso3": "A", "npv5": 100, "bc_ratio": 2}; b = {"iso3": "B", "npv5": 97, "bc_ratio": 3}
    assert rank([a, b])[0]["iso3"] == "B"
