"""화면 생성기(깔때기 결과용)가 결과 파일 형식을 읽어 데이터를 만드는지."""
from kfood_scout.screen_funnel import build_data, render


def _res():
    sc = lambda a: {"attractiveness": a, "ability": a, "safety": a, "attr_groups": {}, "ability_groups": {}, "indicator_pct": {}}
    return {
        "category": {"id": "biscuits", "name_ko": "비스킷류", "hs_codes": ["190531"]}, "protocol": "funnel_v1",
        "top3": ["MYS", "AUS", "PHL"], "funnel": {"pool": 5, "stage1": 4, "stage2": 4, "stage3": 4, "stage4": 4, "stage5": 4},
        "fate": {"MYS": {"stage": 6, "why": "최종 TOP3", "name": "말레이시아"}, "AUS": {"stage": 6, "why": "최종 TOP3", "name": "호주"},
                 "PHL": {"stage": 6, "why": "최종 TOP3", "name": "필리핀"}, "NLD": {"stage": 5, "why": "4위", "name": "네덜란드"},
                 "AGO": {"stage": 1, "why": "최소 시장 규모 · 소득 하한", "name": "Angola"}},
        "final": {"NLD": 60.0, "MYS": 77.1, "AUS": 75.3, "PHL": 75.0},
        "mc_top3_pct": {"MYS": 97.5, "AUS": 93.0, "PHL": 73.6, "AGO": 0.0},
        "shock_top3": {"a": ["MYS", "AUS", "PHL"], "b": ["MYS", "AUS", "NLD"]}, "shocks": {"a": "충격A", "b": "충격B"},
        "shock_npv": {"a": {"MYS": 1.0}, "b": {"MYS": 2.0}},
        "scores": {c: sc(50) for c in ["MYS", "AUS", "PHL", "NLD"]},
        "economics": {c: {"npv5": 10.0, "bc_ratio": 3.0} for c in ["MYS", "AUS", "PHL", "NLD"]},
        "indicators": {c: {} for c in ["MYS", "AUS", "PHL", "NLD", "AGO"]},
    }


def test_build_data():
    d = build_data(_res(), {"frozen": "2026-11-03"}, {"factors": [{"status": "data"}, {"status": "human", "factor": "x"}]},
                   {"decisions": {"MYS": {"conditions": ["할랄"]}}}, {"names_ko": {"AGO": "앙골라"}}, {})
    assert d["order"] == ["MYS", "AUS", "PHL", "NLD"]
    assert d["shocks_same"] == 1
    assert dict(d["s1_why"]) == {"최소 시장 규모": 1, "소득 하한": 1}
    assert d["ko"]["AGO"] == "앙골라" and "AGO" not in d["mc"]
    assert d["checklist"]["human"] == 1
    assert "__DATA__" not in render(d)
