"""결과 화면: 엔진 결과·레드팀 카드·설정에서 데이터를 만들고 HTML 에 넣는지."""
import json

import yaml

from kfood_scout import screen
from kfood_scout.config import ROOT


def _res():
    inds = [{"id": "a", "name": "지표A", "group": "성장성"}, {"id": "b", "name": "지표B", "group": "트렌드"},
            {"id": "c", "name": "지표C", "group": "수출입"}]
    det = [{"id": i["id"], "group": i["group"], "value": 1.0, "unit": "%", "pct_all": 80.0, "rank_all": 3,
            "missing": False, "w_in_group": 1.0, "w_total": 0.33} for i in inds]
    b = lambda iso, st, p, mr: {"iso3": iso, "name": iso, "overall_rank": 1, "kor_exports_2024_usd": 1e6,
                                "groups_pct_in_pool": {"성장성": 90, "트렌드": 80, "수출입": 70}, "status": st,
                                "warn": [], "unknown": [], "boot_mean_rank": mr, "top3_prob": p, "reasons": ["지표A(상위 5%)"],
                                "group_score": {"성장성": 80.0, "트렌드": 80.0, "수출입": 80.0}, "detail": det}
    return {"protocol": "p", "filter": "f", "indicators": inds, "windows": {"2010": 40}, "dev": {}, "sealed": {},
            "B": 200, "group_weights": {"성장성": .4, "트렌드": .4, "수출입": .2}, "third_over_fourth_pct": 70.0,
            "n_all": 6, "n_pool": 5,
            "board": [b("PHL", [], 100.0, 1.0), b("MYS", [], 90.0, 2.0), b("SGP", [], 70.0, 3.0), b("NLD", [], 20.0, 4.0),
                      b("USA", ["이미 한국 과자 수출 상위 5개국(지키고 키울 시장)"], None, None),
                      b("CHN", ["롯데 기진출국"], None, None)]}


def test_build_data_uses_card_over_fallback():
    cfg = yaml.safe_load((ROOT / "config" / "screen" / "screen.yaml").read_text())
    cards = {"PHL": {"verdict": "조건부 진출", "conditions": ["조건1"], "go_line": "진출한다", "summary": "", "cons": [], "pros": [],
                     "source": "레드팀 카드"}}
    d = screen.build_data(_res(), cfg, cards, {})
    assert [c["iso"] for c in d["cands"]][:3] == ["PHL", "MYS", "SGP"]
    assert d["dec"]["PHL"]["verdict"] == "조건부 진출" and d["dec"]["PHL"]["source"] == "레드팀 카드"
    assert d["dec"]["MYS"]["source"].startswith("레드팀 장부")        # 카드 없으면 설정의 대체 판정
    assert d["cands"][0]["hits"] == 200 and d["cnt"] == {"큰시장": 1, "기진출": 1}
    assert d["detail"]["PHL"]["rows"][0]["name"] == "지표A"
    html = screen.render(d)
    assert "__DATA__" not in html and "필리핀" in html


def test_parse_board():
    md = ("## 2\n### 필리핀 (PHL) — 주의\n\n총평 문장.\n\n- [중간·관세] 반론 문장. — [A 2025-01-01](https://a.example)\n\n"
          "반박(진출 지지 근거):\n- 지지 문장. — [B](https://b.example)\n\n## 3. 다음\n")
    r = screen.parse_board(md)["PHL"]
    assert r["summary"] == "총평 문장." and r["cons"][0]["src"][0]["u"] == "https://a.example"
    assert r["pros"][0]["t"] == "지지 문장."
