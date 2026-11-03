"""합성 원천으로 study 전체 흐름(저장소 → 축 조합 → 비교)이 돌아가는지, 재수집/재계산을 피하는지 확인."""
import numpy as np
import pandas as pd

from kfood_scout import compare, store, study

ISOS = [f"C{i:02d}" for i in range(60)]
CALLS = []


def _fake_ct(flow):
    def f(hs, years):
        CALLS.append((flow, hs, tuple(years)))
        rng = np.random.default_rng(abs(hash((flow, hs))) % 2**32)
        rows = []
        for i, c in enumerate(ISOS):
            base, g = rng.uniform(2e5, 5e7), rng.normal(0.05, 0.08)
            rows += [(c, y, base * (1 + g) ** (y - 2000)) for y in years]
        return pd.DataFrame(rows, columns=["iso3", "year", "value"])
    return f


def _fake_wb(code, start, end):
    rng = np.random.default_rng(abs(hash(code)) % 2**32)
    rows = [(c, y, rng.uniform(1e6, 2e8) if code == "SP.POP.TOTL" else rng.uniform(5, 50)) for c in ISOS for y in range(start, end + 1)]
    return pd.DataFrame(rows, columns=["iso3", "year", "value"]).assign(series=f"WB:{code}")


def test_study_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE", tmp_path / "store")
    monkeypatch.setattr(study, "ROOT", tmp_path)
    monkeypatch.setattr(compare, "ROOT", tmp_path)
    monkeypatch.setattr(store, "FETCHERS", {k: _fake_ct(k) for k in ("M", "X", "KOR_X")})
    monkeypatch.setattr(store.worldbank, "fetch_series", _fake_wb)
    monkeypatch.setattr(store, "countries", lambda fetch=True: pd.DataFrame({"iso3": ISOS, "name": ISOS}))

    p = study.plan("lotte_top5")
    assert len(p) == 5 and all(r["pending_calls"] > 0 for r in p)
    res = study.run_study("lotte_top5", log=lambda *a: None)
    assert len(res) == 5 and all(r.get("error") is None for r in res.values())
    n_calls = len(CALLS)
    # 재실행: 수집 0회, 계산 재사용
    study.run_study("lotte_top5", log=lambda *a: None)
    assert len(CALLS) == n_calls
    assert sum(r["pending_calls"] for r in study.plan("lotte_top5")) == 0

    c = compare.compare("lotte_top5")
    base = [r for r in c["runs"] if r["combo"]["category"] == "dry_confectionery"][0]
    assert base["vs_baseline"]["top10_overlap"] == 10
    assert abs(base["vs_baseline"]["forecast_rank_corr"] - 1) < 1e-9
    assert len(c["consensus"]) > 20


def test_axis_override_and_unknown_axis():
    s = study.load_study("lotte_top5")
    s["overrides"] = [{"when": {"category": "edible_fats"}, "set": {"criterion.universe.min_korea_exports_usd": 1}}]
    runs = {r["combo"]["category"]: r for r in study.expand(s)}
    assert runs["edible_fats"]["ctx"]["criterion"]["universe"]["min_korea_exports_usd"] == 1
    assert runs["ice_cream"]["ctx"]["criterion"]["universe"]["min_korea_exports_usd"] == 100000
    s["axes"]["target"] = ["growth"]
    s["targets"] = {"growth": {"kind": "log"}}
    assert all(r["ctx"]["criterion"]["target"]["kind"] == "log" for r in study.expand(s))
