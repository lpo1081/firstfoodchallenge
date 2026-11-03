"""합성 데이터: 한국 수출 증가가 '한국산 비중 변화'와 '인구'로 결정되는 가상 세계에서 롤링 역산이 그 신호를 찾는지 확인."""
import numpy as np
import pandas as pd

from kfood_scout import rolling
from kfood_scout.config import load_criterion


def synthetic(seed=1):
    rng = np.random.default_rng(seed)
    isos = [f"C{i:02d}" for i in range(80)]
    rows = []
    for c in isos:
        pop0 = rng.uniform(2e6, 3e8); imp0 = rng.uniform(5e6, 1e9); kor0 = rng.uniform(2e5, 3e7)
        g_imp, g_kor = rng.normal(0.05, 0.04), rng.normal(0.06, 0.08)
        youth, cons, urb = rng.uniform(15, 45), rng.uniform(800, 3e4), rng.uniform(20, 80)
        for y in range(2000, 2026):
            t = y - 2000
            kor = kor0 * (1 + g_kor) ** t
            rows += [(c, y, "WB:SP.POP.TOTL", pop0 * 1.01 ** t), (c, y, "CT:dry_confectionery:M", imp0 * (1 + g_imp) ** t),
                     (c, y, "CT:dry_confectionery:KOR_X", kor), (c, y, "WB:NE.CON.PRVT.PC.KD", cons * 1.02 ** t),
                     (c, y, "WB:SP.URB.TOTL.IN.ZS", urb + 0.3 * t), (c, y, "WB:SP.POP.0014.TO.ZS", youth),
                     (c, y, "WB:NY.GDP.PCAP.PP.KD", cons * 2)]
    return pd.DataFrame(rows, columns=["iso3", "year", "series", "value"]), pd.DataFrame({"iso3": isos, "name": isos})


def test_rolling_runs_and_finds_signal():
    panel, countries = synthetic()
    crit = load_criterion("k_export")
    out = rolling.run(panel, countries, crit, "dry_confectionery", starts=(2010, 2013, 2016, 2019), forecast_year=2022,
                      existing={"C01"})
    assert len(out["windows"]) == 4 and out["windows"][0]["n"] > 50
    # 한국 수출 증가액은 한국 수출 규모·성장률로 결정되므로 수출입 그룹이 큰 비중이어야 함
    assert out["windows"][-1]["groups"]["수출입"] > 0.5
    assert out["out_of_sample"][0]["X_prev"] > out["out_of_sample"][0]["equal"]
    assert abs(sum(out["XX"].values()) - 1) < 0.01
    assert len(out["forecast_XX"]) > 50


def test_combine_options_and_top_probability():
    panel, countries = synthetic()
    crit = load_criterion("k_export")
    out = rolling.run(panel, countries, crit, "dry_confectionery", starts=(2010, 2013, 2016, 2019), forecast_year=2022,
                      combine="latest", top_prob_B=20)
    assert out["combine"] == "latest"
    assert out["XX"] == out["X_latest"]  # 기본: 추세 연장 대신 최신 X
    assert {"XX_latest", "XX_mean2", "XX_extrapolate", "X_prev"} <= set(out["xx_test"])
    probs = [c["prob"]["top3"] for c in out["forecast_XX"]]
    assert abs(sum(probs) - 300) < 1e-6  # 재표본마다 정확히 3개국
    assert all(0 <= p <= 100 for p in probs)
    assert {c["tier"] for c in out["forecast_XX"]} == {"큰 시장", "중간 시장", "작은 시장"}
    assert min(c["tier_rank"] for c in out["forecast_XX"] if c["tier"] == "작은 시장") == 1


def test_local_market_axis_uses_total_imports_as_target():
    panel, countries = synthetic()
    imp = panel[panel.series == "CT:dry_confectionery:M"].copy()
    imp["series"], imp["value"] = "EX:unido_snack_consumption", imp["value"] * 3  # 합성 실소비 = 수입의 3배
    panel = pd.concat([panel, imp], ignore_index=True)
    crit = load_criterion("local_market")
    out = rolling.run(panel, countries, crit, "dry_confectionery", starts=(2010, 2013, 2016, 2019), forecast_year=2022, top_prob_B=0)
    c = out["forecast_XX"][0]
    assert c["target_base_usd"] != c["kor_exports_usd"]  # 정답·체급 기준이 한국 수출이 아니라 전체 수입
    assert "korea_exports_size" not in out["XX"]
    assert abs(c["target_base_usd"] / 3 - panel[(panel.series == "CT:dry_confectionery:M") & (panel.iso3 == c["iso3"])
                                               & (panel.year.isin([2021, 2022]))].value.mean()) < 1  # 정답 = 외부 원천(실소비)


def test_fetch_unido_parses_response(monkeypatch):
    import requests
    from kfood_scout.sources import external

    class R:
        def __init__(self, js, code=200):
            self._js, self.status_code, self.text = js, code, ""

        def json(self):
            return self._js

    meta = {"id": 153, "countries": [{"iso3": "PHL", "c": "608"}, {"iso3": "IND", "c": "356"}]}
    data = {"608": [{"p": "2020", "a": "1071", "v": 10.0, "c": "608"}, {"p": "2020", "a": "1073", "v": 5.0, "c": "608"},
                    {"p": "2021", "a": "1071", "v": 12.0, "c": "608"}],
            "356": [{"p": "2020", "a": "1079", "v": 99.0, "c": "356"}]}
    sent = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: R(meta))
    monkeypatch.setattr(requests, "post", lambda url, json, timeout: (sent.append(json), R({"data": data[json["countryCode"]]}))[1])
    monkeypatch.setattr(external.time, "sleep", lambda s: None)
    df = external.fetch("unido_snack_consumption", [2020, 2021], log=lambda *a: None)
    assert sent[0]["variableCode"] == "107" and sent[0]["activityCodes"] == ["1071", "1073"]
    got = {(r.iso3, r.year): r.value for r in df.itertuples()}
    assert got == {("PHL", 2020): 15.0, ("PHL", 2021): 12.0}  # 1071+1073 합산, 다른 활동코드(1079)는 제외
