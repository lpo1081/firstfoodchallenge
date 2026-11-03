"""레드팀(비판 에이전트)과 가설 장부: 가짜 Claude 응답으로 판정 규칙을 확인(비용 0)."""
import datetime as dt
import json
from types import SimpleNamespace as NS

from kfood_scout.agent import board, critic as cr, loop
from kfood_scout.agent import propose as pr
from kfood_scout.config import load_criterion_raw

TODAY = dt.date(2026, 11, 3)


def _usage():
    return NS(input_tokens=20000, output_tokens=1500, cache_read_input_tokens=0, cache_creation_input_tokens=0,
              server_tool_use=NS(web_search_requests=2))


def _ev(url, date="2026-05", pub="뉴스"):
    return {"url": url, "title": "t", "publisher": pub, "date": date}


CARD = {
    "summary": "정치 불안과 할랄 규제가 걸림돌.",
    "objections": [
        {"claim": "쿠데타 위험", "category": "정치·치안", "severity": "치명",
         "evidence": [_ev("https://a.com/1"), _ev("https://b.org/2")], "quantifiable": True, "indicator_idea": "WGI 정치안정성",
         "condition": "진출 보류", "mitigable": False},
        {"claim": "할랄 인증 의무화", "category": "규제·통관·인증", "severity": "치명",
         "evidence": [_ev("https://a.com/3")], "quantifiable": False, "indicator_idea": "",
         "condition": "KMF 할랄 인증 제품부터 출시", "mitigable": True},
        {"claim": "지어낸 기사", "category": "경제·환율", "severity": "치명",
         "evidence": [_ev("https://fake.example/made-up")], "quantifiable": True, "indicator_idea": "환율 변동성",
         "condition": "", "mitigable": True},
        {"claim": "옛날 기사", "category": "관세·무역협정", "severity": "중간",
         "evidence": [_ev("https://b.org/old", date="2019-01")], "quantifiable": False, "indicator_idea": "",
         "condition": "", "mitigable": True},
    ],
    "support": [{"claim": "한류 열풍", "evidence": [_ev("https://c.net/4")]}],
    "go_line": "진출하지 않는다.",
}


class FakeClient:
    """검색 1번(결과 5건) → submit_critique 제출."""

    def __init__(self, card=CARD):
        self.n, self.card = 0, card
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.n += 1
        if self.n % 2 == 1:
            res = [NS(type="web_search_result", url=u, title="t", page_age="2026-04-01")
                   for u in ("https://a.com/1", "https://b.org/2/", "https://a.com/3", "https://b.org/old", "https://c.net/4")]
            return NS(model="claude-opus-5-5", usage=_usage(), stop_reason="pause_turn", content=[
                NS(type="server_tool_use", name="web_search", input={"query": "country snack import ban"}),
                NS(type="web_search_tool_result", content=res)])
        return NS(model="claude-opus-5-5", usage=_usage(), stop_reason="tool_use",
                  content=[NS(type="tool_use", id="s1", name="submit_critique", input=self.card)])


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "OUT", tmp_path / "critic")
    monkeypatch.setattr(cr, "SEEDS", tmp_path / "critic" / "seeds.json")
    monkeypatch.setattr(cr.Budget, "__init__", _budget_init(tmp_path))


def _budget_init(tmp_path):
    orig = cr.Budget.__init__

    def init(self, limit_usd=3.0, run=None, path=None):
        orig(self, limit_usd, run, tmp_path / "costs.jsonl")
    return init


def test_judge_rules(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s = cr.run(countries="IDN", client=FakeClient(), today=TODAY, log=lambda *a: None)
    card = json.loads((tmp_path / "critic" / "IDN.json").read_text())
    claims = {o["claim"]: o for o in card["objections"]}
    assert "지어낸 기사" not in claims and "옛날 기사" not in claims      # 검색에 없는 주소·오래된 기사는 버림
    assert claims["쿠데타 위험"]["severity"] == "치명"                    # 출처 2곳 → 치명 인정
    assert claims["할랄 인증 의무화"]["severity"] == "중간"               # 출처 1곳 → 중간으로 낮춤
    assert card["verdict"] == "배제" and s["verdicts"] == {"IDN": "배제"}   # 감당 못 하는 치명 반론
    assert len(card["dropped"]) == 2 and len(card["support"]) == 1
    seeds = json.loads((tmp_path / "critic" / "seeds.json").read_text())
    assert [x["indicator_idea"] for x in seeds] == ["WGI 정치안정성"]   # 버린 반론의 씨앗은 남기지 않음


def test_cache_and_budget(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fc = FakeClient()
    cr.run(countries="IDN", client=fc, today=TODAY, log=lambda *a: None)
    n = fc.n
    s = cr.run(countries="IDN,PHL", client=fc, budget_usd=0.05, today=TODAY, log=lambda *a: None)
    assert fc.n == n                       # IDN 은 캐시 재사용, PHL 은 예산 부족으로 시작 안 함
    assert s["checked"] == ["IDN"] and s["skipped"] == ["PHL"]


def test_ranking_file(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("rank,iso3\n1,phl\n2,MNG\n3,SGP\n")
    c = cr.candidates(cr.load_cfg(), ranking=str(p), top=2)
    assert [x["iso3"] for x in c] == ["PHL", "MNG"] and c[0]["name_ko"] == "필리핀"
    j = tmp_path / "r.json"
    j.write_text(json.dumps({"ranking": [{"iso3": "IDN"}, {"iso3": "KEN", "name": "Kenya"}]}))
    c = cr.candidates(cr.load_cfg(), ranking=str(j))
    assert [x["iso3"] for x in c] == ["IDN", "KEN"] and c[1]["name_en"] == "Kenya"  # 설정에 없는 나라는 파일 이름 사용


def test_seeds_reach_proposer_and_board(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cr.run(countries="IDN", client=FakeClient(), today=TODAY, log=lambda *a: None)
    prompt = pr.build_prompt(load_criterion_raw("k_export"), [], [], 3, cr.load_seeds())
    assert "레드팀" in prompt and "WGI 정치안정성" in prompt
    assert "레드팀" not in pr.build_prompt(load_criterion_raw("k_export"), [], [], 3, [])
    monkeypatch.setattr(loop, "out_dir", lambda c: tmp_path)
    (tmp_path / "ledger.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"hypothesis": "kculture", "statement": "한류", "status": "accepted", "oos": {"mean_delta": 0.11, "p_better": 1.0}, "at": "x"},
        {"hypothesis": "auto_critic_political_stability", "statement": "정치 안정성", "proposed_by": "llm:x",
         "status": "rejected", "oos": {"mean_delta": -0.01, "p_better": 0.4}, "at": "x"},
        {"hypothesis": "auto", "status": "auto_end", "reason": "", "at": "x"}]))
    md = board.build("dry_confectionery")
    assert "레드팀 반론→AI" in md and "| **배제** |" in md and "진출하지 않는다" in md and "WGI 정치안정성" in md and "| kculture | 사람 |" in md
    assert (tmp_path / "board.md").exists()


RULES = cr.load_cfg()["rules"]


def _o(sev, cond="", mit=True):
    return {"claim": f"{sev} 반론", "category": "경제·환율", "severity": sev, "condition": cond, "mitigable": mit}


def test_decision_is_go_conditional_or_exclude():
    assert cr.decide({"objections": [_o("낮음")]}, RULES)["verdict"] == "진출"
    d = cr.decide({"objections": [_o("중간", "비스킷만 출시"), _o("치명", "할랄 인증 먼저"), _o("낮음", "x")]}, RULES)
    assert d["verdict"] == "조건부 진출" and d["conditions"] == ["할랄 인증 먼저", "비스킷만 출시"]   # 심각한 것부터
    assert cr.decide({"objections": [_o("치명", "", False), _o("중간", "a")]}, RULES)["verdict"] == "배제"


class FakeCond:
    """옛 카드 조건 채우기: 검색 없이 JSON 한 번."""

    def __init__(self):
        self.n = 0
        self.messages = NS(create=self.create)

    def create(self, **kw):
        self.n += 1
        js = {"items": [{"index": 0, "condition": "RCEP 원산지로 관세 낮추고 비스킷부터", "mitigable": True}],
              "go_line": "진출한다. 비스킷 중심으로."}
        return NS(model="claude-opus-5-5", usage=_usage(), stop_reason="end_turn",
                  content=[NS(type="text", text=json.dumps(js, ensure_ascii=False))])


def test_backfill_turns_old_caution_into_conditions(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / "critic").mkdir()
    old = {"iso3": "PHL", "name_ko": "필리핀", "checked": "2026-11-03", "verdict": "주의",
           "objections": [{"claim": "FTA 민감품목", "category": "관세·무역협정", "severity": "중간", "evidence": []}]}
    (tmp_path / "critic" / "PHL.json").write_text(json.dumps(old, ensure_ascii=False))
    (tmp_path / "critic" / "summary.json").write_text(json.dumps({"checked": ["PHL"], "verdicts": {"PHL": "주의"}}))
    fc = FakeCond()
    r = cr.backfill(client=fc, log=lambda *a: None)
    card = json.loads((tmp_path / "critic" / "PHL.json").read_text())
    assert r["verdicts"] == {"PHL": "조건부 진출"} and card["conditions"] == ["RCEP 원산지로 관세 낮추고 비스킷부터"]
    assert card["go_line"].startswith("진출한다") and fc.n == 1
    cr.backfill(client=fc, log=lambda *a: None)
    assert fc.n == 1                                   # 이미 채운 카드는 다시 부르지 않음(무료)
