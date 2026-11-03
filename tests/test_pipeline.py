"""합성 데이터로 파이프라인 로직 검증 (실제 결과 아님).

정답 세트 국가들이 '유소년 비중'이 높게 만들어진 가상 세계에서
- 미래 데이터가 섞이지 않는지,
- 역산이 동작하는지,
- 후보 지표 검토가 유소년 비중을 잡아내는지 확인한다.
"""
import numpy as np
import pandas as pd

from kfood_scout import validation
from kfood_scout.config import load_criterion
from kfood_scout.indicators import compute_indicator
from kfood_scout.scoring import score


def synthetic(seed=0):
    rng = np.random.default_rng(seed)
    isos = [f"C{i:02d}" for i in range(60)]
    years = range(1990, 2025)
    rows = []
    youth = {c: rng.uniform(15, 45) for c in isos}
    for c in ["C01", "C02", "C03"]:
        youth[c] = 48
    for c in isos:
        pop0, imp0, cons0, urb0 = rng.uniform(6e6, 3e8), rng.uniform(1e6, 1e9), rng.uniform(500, 3e4), rng.uniform(20, 80)
        g_imp, g_cons = rng.normal(0.06, 0.05), rng.normal(0.03, 0.02)
        for y in years:
            t = y - 1990
            rows += [
                (c, y, "WB:SP.POP.TOTL", pop0 * 1.015 ** t),
                (c, y, "CT:dry_confectionery:M", imp0 * (1 + g_imp) ** t),
                (c, y, "CT:dry_confectionery:X", imp0 * 0.3),
                (c, y, "WB:NE.CON.PRVT.PC.KD", cons0 * (1 + g_cons) ** t),
                (c, y, "WB:SP.URB.TOTL.IN.ZS", min(95, urb0 + 0.3 * t)),
                (c, y, "WB:SP.POP.0014.TO.ZS", youth[c]),
                (c, y, "WB:NY.GDP.PCAP.PP.KD", cons0 * 2),
                (c, y, "WB:FP.CPI.TOTL.ZG", 5.0),
            ]
    panel = pd.DataFrame(rows, columns=["iso3", "year", "series", "value"])
    countries = pd.DataFrame({"iso3": isos, "name": isos, "region": "X", "income": "X"})
    return panel, countries


def test_no_future_leak():
    panel, _ = synthetic()
    crit = load_criterion("market_growth")
    ind = next(i for i in crit.indicators if i.id == "import_market_cagr")
    a = compute_indicator(panel, ind, "dry_confectionery", 2005)
    panel2 = panel.copy()
    panel2.loc[panel2.year > 2005, "value"] *= 100
    b = compute_indicator(panel2, ind, "dry_confectionery", 2005)
    pd.testing.assert_series_equal(a, b)


def test_score_and_validation():
    panel, countries = synthetic()
    crit = load_criterion("market_growth")
    table, raw, pct = score(panel, countries, crit, "dry_confectionery", 2020)
    assert table["score"].between(0, 100).all()
    assert len(table) == 60
    entries = {"entries": [
        {"iso3": c, "country_ko": c, "year": y, "mode": "x", "detail": "", "sources": [], "include": True}
        for c, y in [("C01", 2005), ("C02", 2010), ("C03", 2015)]]}
    events, inv, cands = validation.run(panel, countries, crit, "dry_confectionery", entries, grid_step=0.1)
    assert inv["best_mean_percentile"] >= inv["default_mean_percentile"]
    assert cands.iloc[0]["id"] == "youth_share"   # 심어둔 신호를 후보 검토가 1순위로 잡아야 함
    assert all(ev["rank"] for ev in events)


def test_simplex():
    W = validation.simplex_grid(5, 0.05)
    assert len(W) == 10626 and np.allclose(W.sum(1), 1)
