"""다른 방법 모듈(kfood_scout.alt) 테스트. 가짜 데이터만 쓰고 네트워크는 쓰지 않는다."""
import numpy as np
import pandas as pd

from kfood_scout.alt import analog, common, gap
from kfood_scout.alt.__main__ import consensus


def test_ppml_recovers_coefficients():
    rng = np.random.default_rng(0)
    n = 400
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    X = np.column_stack([np.ones(n), x1, x2])
    y = rng.poisson(np.exp(1.0 + 0.8 * x1 - 0.5 * x2))
    b = gap.ppml(X, y.astype(float))
    assert abs(b[1] - 0.8) < 0.1 and abs(b[2] + 0.5) < 0.1


def test_km_seoul_manila():
    d = gap.km(*gap.SEOUL, 14.6, 121.0)
    assert 2500 < d < 2700


def _store(tmp_path, monkeypatch, kor_rows):
    d = tmp_path / "comtrade_KOR_X"
    d.mkdir(parents=True)
    pd.DataFrame(kor_rows, columns=["iso3", "year", "value"]).to_csv(d / "190531.csv", index=False)
    monkeypatch.setattr(common, "STORE", tmp_path)


def test_takeoff_rule(tmp_path, monkeypatch):
    rows = [("AAA", y, 1e6 if y < 2010 else 6e6) for y in range(2005, 2016)]      # 2005 1 → 2010 6 : 이륙
    rows += [("BBB", y, 3e6) for y in range(2005, 2016)]                            # 계속 3 : 아님
    _store(tmp_path, monkeypatch, rows)
    cfg = {"hs": ["190531"], "methods": {"analog": {"takeoff": {
        "start_below_musd": 2, "after_years": 5, "end_at_least_musd": 4, "multiple_at_least": 4,
        "first_year": 2005, "last_year": 2010}}}}
    t = analog.takeoffs(cfg)
    assert [(x["iso3"], x["year"]) for x in t] == [("AAA", 2005)]


def test_consensus_counts_methods():
    res = {"m1": {"ranking": [{"iso3": "A"}, {"iso3": "B"}]}, "m2": {"ranking": [{"iso3": "B"}, {"iso3": "C"}]}}
    cons = consensus(res, ["B", "A"], top_n=2, cand=["A", "B", "C"])
    assert cons[0]["iso3"] == "B" and cons[0]["n_top"] == 3
    assert {r["iso3"]: r["n_top"] for r in cons} == {"B": 3, "A": 2, "C": 1}


def test_outputs_only_in_alt_folder():
    assert common.OUT.parts[-2:] == ("outputs", "alt_methods")


def test_failure_rule(tmp_path, monkeypatch):
    from kfood_scout.alt import failure
    rows = [("AAA", y, v) for y, v in zip(range(2005, 2016), [1, 2, 4, 6, 8, 10, 5, 4, 4, 4, 4])]   # 정점 후 반토막
    rows += [("BBB", y, 5.0) for y in range(2005, 2016)]                                              # 평탄
    _store(tmp_path, monkeypatch, [(c, y, v * 1e6) for c, y, v in rows])
    cfg = {"hs": ["190531"], "checks": {"failure": {"rule": {
        "peak_at_least_musd": 3, "fall_within_years": 4, "fall_to_at_most": 0.7, "first_year": 2007, "last_year": 2012}}}}
    assert [x["iso3"] for x in failure.failures(cfg)] == ["AAA"]


def test_timetravel_as_of_moves_windows():
    from kfood_scout.alt import timetravel
    cfg = common.load_cfg()
    c = timetravel.as_of(cfg, 2015)
    assert c["now_year"] == 2015
    assert c["methods"]["follow"]["to_year"] == 2015 and c["methods"]["follow"]["from_year"] == 2010
    assert c["methods"]["analog"]["takeoff"]["last_year"] == 2010
    assert cfg["now_year"] == 2024   # 원본 설정은 그대로
