"""3대 기준 TOP3: 검증 규칙·사전 필터·모델 학습이 설정대로 움직이는지(합성 데이터)."""
import numpy as np
import pandas as pd

from kfood_scout import three
from kfood_scout.config import load_yaml


def test_protocol_and_filter_are_frozen_files():
    p = load_yaml("validation", "three_criteria_protocol.yaml")
    f = load_yaml("filters", "hard_filter.yaml")
    assert p["windows"]["sealed_test"] not in p["windows"]["dev_tests"]  # 봉인 시험은 모델 선택에 안 씀
    assert {r["id"] for r in f["rules"]} >= {"sanctions", "political_instability"}


def test_hard_filter_list_and_wgi():
    filt = {"rules": [
        {"id": "s", "kind": "list", "action": "exclude", "name_ko": "제재", "iso3": ["IRN"]},
        {"id": "p", "kind": "wgi", "series": "PV.EST", "years": 3, "exclude_below": -1.5, "warn_below": -1.0, "name_ko": "정치 불안"},
    ]}
    rows = [(c, y, "WB:PV.EST", v) for c, v in (("AAA", -2.0), ("BBB", -1.2), ("CCC", 0.5)) for y in (2021, 2022, 2023)]
    panel = pd.DataFrame(rows, columns=["iso3", "year", "series", "value"])
    r = three.hard_filter(filt, panel, ["AAA", "BBB", "CCC", "IRN"], 2024)
    assert r["AAA"]["exclude"] and r["BBB"]["warn"] and not r["CCC"]["exclude"] and not r["CCC"]["warn"]
    assert r["IRN"]["exclude"] == ["제재"] and r["IRN"]["unknown"]  # 값 없는 나라는 '미확인'
    # 정치 안정 데이터가 아예 없으면 규칙을 건너뛰고 미확인으로 표시
    r2 = three.hard_filter(filt, panel[panel.iso3 == "none"], ["CCC"], 2024)
    assert not r2["CCC"]["exclude"] and r2["CCC"]["unknown"]


def test_variants_find_signal():
    rng = np.random.default_rng(0)
    ids = ["a1", "a2", "b1", "b2", "c1"]
    gmap = {"a1": "성장성", "a2": "성장성", "b1": "트렌드", "b2": "트렌드", "c1": "수출입"}
    Ps, ys = [], []
    for _ in range(4):
        P = pd.DataFrame(rng.uniform(0, 100, (60, 5)), columns=ids)
        ys.append(pd.Series(P["b1"] * 2 + P["a1"] + rng.normal(0, 10, 60)))
        Ps.append(P)
    m = three.VARIANTS["3기준_지표·기준비중 모두학습"](Ps, ys, ids, gmap)
    assert abs(m.w.sum() - 1) < 1e-6 and m.w["b1"] > m.w["b2"] and m.w["a1"] > m.w["a2"]
    assert m.gw["트렌드"] > m.gw["수출입"]
    only = three.VARIANTS["트렌드만"](Ps, ys, ids, gmap)
    assert set(only.w[only.w > 0].index) <= {"b1", "b2"}
    assert three._simplex(3, 0.5).shape == (3, 6)
