"""합성 세계: 한국 수출 성장이 'K-문화 관심도'에 좌우되는 세계에서
에이전트가 K-문화 가설은 채택하고, 아무 의미 없는 지표 가설은 기각하는지 확인."""
import numpy as np
import pandas as pd

from kfood_scout import store
from kfood_scout.agent import evaluate as ev
from kfood_scout.agent import loop
from kfood_scout.config import load_criterion_raw

ISOS = [f"C{i:02d}" for i in range(90)]


def world(seed=3):
    rng = np.random.default_rng(seed)
    rows = []
    for c in ISOS:
        pop0, imp0, kor = rng.uniform(2e6, 3e8), rng.uniform(5e6, 1e9), rng.uniform(2e6, 4e6)
        g_imp = rng.normal(0.05, 0.04)
        youth, cons, urb = rng.uniform(15, 45), rng.uniform(800, 3e4), rng.uniform(20, 80)
        k = rng.uniform(0, 100)
        for y in range(2003, 2026):
            t = y - 2003
            k = float(np.clip(0.5 * k + 0.5 * rng.uniform(0, 100), 0, 100))  # K-문화 관심도: 해마다 크게 바뀜
            g = 0.02 + 0.0025 * k + rng.normal(0, 0.02)             # 수출 성장은 관심도가 결정
            kor *= 1 + g
            rows += [(c, y, "WB:SP.POP.TOTL", pop0 * 1.01 ** t), (c, y, "CT:dry_confectionery:M", imp0 * (1 + g_imp) ** t),
                     (c, y, "CT:dry_confectionery:KOR_X", kor), (c, y, "WB:NE.CON.PRVT.PC.KD", cons * 1.02 ** t),
                     (c, y, "WB:SP.URB.TOTL.IN.ZS", urb + 0.3 * t), (c, y, "WB:SP.POP.0014.TO.ZS", youth),
                     (c, y, "WB:NY.GDP.PCAP.PP.KD", cons * 2), (c, y, "EX:gtrends_kpop", k),
                     (c, y, "EX:noise", rng.uniform(0, 100))]
    return pd.DataFrame(rows, columns=["iso3", "year", "series", "value"]), pd.DataFrame({"iso3": ISOS, "name": ISOS})


KPOP = {"id": "kpop", "statement": "K-pop 관심이 높으면 수출이 는다", "indicators": [
    {"id": "kpop_interest", "name_ko": "K-pop 관심도", "group": "소비트렌드", "source": "external", "series": "gtrends_kpop",
     "transform": "level", "window": 1, "direction": 1}]}
NOISE = {"id": "noise", "statement": "의미 없는 지표", "indicators": [
    {"id": "noise_level", "name_ko": "잡음", "group": "소비트렌드", "source": "external", "series": "noise",
     "transform": "level", "window": 1, "direction": 1}]}
FAST = dict(starts=tuple(range(2012, 2020)), n_fit=1500, B=150)


def test_accepts_real_signal_and_rejects_noise():
    panel, countries = world()
    base = load_criterion_raw("k_export")
    good = ev.evaluate(panel, countries, base, KPOP, "dry_confectionery", **FAST)
    bad = ev.evaluate(panel, countries, base, NOISE, "dry_confectionery", **FAST)
    assert good["status"] == "accepted", good["reason"]
    assert bad["status"] in ("rejected", "weak"), bad["reason"]
    assert good["oos"]["mean_delta"] > bad["oos"]["mean_delta"]
    assert np.mean(list(good["partial_corr"]["kpop_interest"].values())) > 0.3   # 소득 통제 후에도 남음
    assert "채택" in good["reason"]


def test_missing_data_is_flagged():
    panel, countries = world()
    panel = panel[panel.series != "EX:gtrends_kpop"]
    r = ev.evaluate(panel, countries, load_criterion_raw("k_export"), KPOP, "dry_confectionery", **FAST)
    assert r["status"] == "data_needed"


def test_loop_with_llm_stub_and_adopt(tmp_path, monkeypatch):
    panel, countries = world()
    monkeypatch.setattr(loop, "ROOT", tmp_path)
    monkeypatch.setattr(loop, "HYP_DIR", tmp_path / "hyp")
    monkeypatch.setattr(loop, "CONFIG", tmp_path)
    (tmp_path / "criteria").mkdir()
    monkeypatch.setattr(loop, "panel_for", lambda *a, **k: panel)
    monkeypatch.setattr(store, "countries", lambda fetch=True: countries)
    monkeypatch.setattr(loop.pr.external, "catalog",
                        lambda: [{"series": "gtrends_kpop"}, {"series": "noise"}])
    seen = {}

    def llm(prompt):
        seen["prompt"] = prompt
        mk = lambda h: {**h, "rationale": "테스트", "group": "소비트렌드", "new_source_needed": "",
                        "indicators": [{**i, "flow": ""} for i in h["indicators"]]}
        bad_src = {**mk(NOISE), "id": "unknown", "indicators": [{**mk(NOISE)["indicators"][0], "series": "tiktok"}]}
        return {"hypotheses": [mk(KPOP), mk(NOISE), bad_src]}

    led = loop.loop(rounds=1, llm=llm, fetch=False, log=lambda *a: None, **FAST)
    st = {r["hypothesis"]: r["status"] for r in led}
    assert st["auto_kpop"] == "accepted" and st["auto_noise"] in ("rejected", "weak") and st["auto_unknown"] == "data_needed"
    assert "모델이 놓친 나라" in seen["prompt"]
    rep = loop.adopt(fetch=False, log=lambda *a: None, **FAST)
    assert "kpop_interest" in rep["added"] and rep["written"]
    assert (tmp_path / "criteria" / "k_export_agent.yaml").exists()
    assert "채택" in loop.report()


def test_partial_data_tests_available_indicators():
    panel, countries = world()
    hyp = {"id": "mix", "indicators": KPOP["indicators"] + [{**NOISE["indicators"][0], "id": "visitors", "series": "kto_visitors"}]}
    r = ev.evaluate(panel, countries, load_criterion_raw("k_export"), hyp, "dry_confectionery", **FAST)
    assert r["data_needed"] == ["visitors"] and r["status"] == "accepted"


def test_degenerate_values_are_excluded():
    panel, countries = world()
    m = panel.series == "EX:gtrends_kpop"
    panel.loc[m, "value"] = 100.0  # 구글 트렌드 0/100 퇴화 재현
    r = ev.evaluate(panel, countries, load_criterion_raw("k_export"), KPOP, "dry_confectionery", **FAST)
    assert r["status"] == "data_needed" and r["degenerate"] == ["kpop_interest"]


def test_auto_prefix_once(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "HYP_DIR", tmp_path)
    assert loop.save_hypothesis({"id": "auto_reexport_hub", "indicators": []}) == "auto_reexport_hub"


# ---------- 자율 실행 + 데이터 탐색 에이전트 (가짜 Claude 응답으로, 비용 0) ----------
from types import SimpleNamespace as NS  # noqa: E402

from kfood_scout.agent import cost, scout as sc  # noqa: E402
from kfood_scout.sources import external  # noqa: E402


def _usage():
    return NS(input_tokens=10000, output_tokens=2000, cache_read_input_tokens=0, cache_creation_input_tokens=0,
              server_tool_use=NS(web_search_requests=2))


class FakeClient:
    """정해진 순서로 '검색 → 명세 시험(실패) → 고친 명세 시험(통과) → 등록' 하는 가짜 Claude."""

    def __init__(self):
        self.n = 0
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.n += 1
        spec = {"format": "csv", "url": "https://example.org/kpop.csv", "wb_indicator": "", "zip_member": "", "sheet": "",
                "skiprows": 0, "json_path": "", "iso3_col": "iso3", "country_col": "", "year_col": "year",
                "value_col": "VALUE_WRONG", "wide_years": False, "filters": []}
        steps = {
            1: [NS(type="server_tool_use", name="web_search", input={"query": "k-pop interest by country yearly"}),
                NS(type="tool_use", id="t1", name="try_source", input={"spec": spec})],
            2: [NS(type="tool_use", id="t2", name="try_source", input={"spec": dict(spec, value_col="value")})],
            3: [NS(type="tool_use", id="t3", name="register_source",
                   input={"desc": "K-pop 관심도(테스트)", "publisher": "테스트", "notes": "합성"})],
        }
        return NS(model="claude-opus-5-5", usage=_usage(), stop_reason="tool_use", content=steps[self.n])


def test_scout_registers_after_fixing_spec(tmp_path, monkeypatch):
    panel, _ = world()
    data = panel[panel.series == "EX:gtrends_kpop"][["iso3", "year", "value"]]
    monkeypatch.setattr(external, "RAW", tmp_path / "raw")
    monkeypatch.setattr(sc, "AUTO_SOURCES", tmp_path / "auto.yaml")
    monkeypatch.setattr(external, "AUTO_SOURCES", tmp_path / "auto.yaml")
    monkeypatch.setattr(external, "SOURCES", dict(external.SOURCES))  # 테스트 등록이 다른 테스트로 새지 않게
    b = cost.Budget(1.0, path=tmp_path / "costs.jsonl")
    hyp = {"id": "auto_k", "statement": "s", "indicators": [{"id": "x", "source": "external", "series": "kpop_new"}]}
    r = sc.scout("kpop_new", "K-pop 관심도", hyp, list(range(2005, 2025)), b, client=FakeClient(),
                 log=lambda *a: None, loader=lambda spec, years: data)
    assert r["status"] == "registered"
    assert [t.get("ok") for t in r["trace"] if t["tool"] == "try_source"] == [False, True]  # 실패 → 고쳐서 통과
    assert "kpop_new" in {c["series"] for c in external.catalog()}
    assert (tmp_path / "raw" / "auto_kpop_new.csv").exists()
    assert b.calls == 3 and abs(b.spent - 3 * (0.04 + 0.04 + 0.02)) < 1e-9  # 입력 1만·출력 2천 토큰 + 검색 2회


def test_scout_rejects_register_without_passing(tmp_path):
    class Bad(FakeClient):
        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                c = [NS(type="tool_use", id="t1", name="register_source", input={"desc": "d", "publisher": "p", "notes": ""})]
            else:
                c = [NS(type="tool_use", id="t2", name="give_up", input={"reason": "없음", "tried": "-"})]
            return NS(model="claude-opus-5-5", usage=_usage(), stop_reason="tool_use", content=c)
    b = cost.Budget(1.0, path=tmp_path / "c.jsonl")
    r = sc.scout("zzz", "", {"id": "h"}, list(range(2005, 2025)), b, client=Bad(), log=lambda *a: None)
    assert r["status"] == "gave_up"


def test_budget_stops_scout(tmp_path):
    b = cost.Budget(0.2, path=tmp_path / "c.jsonl")
    r = sc.scout("zzz", "", {"id": "h"}, list(range(2005, 2025)), b, client=FakeClient(), log=lambda *a: None)
    assert r["status"] == "budget" and b.spent <= 0.2


def test_auto_finds_data_then_stops_on_plateau(tmp_path, monkeypatch):
    panel, countries = world()
    k = panel[panel.series == "EX:gtrends_kpop"].assign(series="EX:kpop_new")
    panel = pd.concat([panel, k])
    monkeypatch.setattr(loop, "ROOT", tmp_path)
    monkeypatch.setattr(loop, "HYP_DIR", tmp_path / "hyp")
    monkeypatch.setattr(loop, "CONFIG", tmp_path)
    (tmp_path / "criteria").mkdir()
    monkeypatch.setattr(loop, "panel_for", lambda *a, **kw: panel)
    monkeypatch.setattr(store, "countries", lambda fetch=True: countries)
    monkeypatch.setattr(external, "RAW", tmp_path / "raw")
    monkeypatch.setattr(sc, "AUTO_SOURCES", tmp_path / "auto.yaml")
    monkeypatch.setattr(external, "AUTO_SOURCES", tmp_path / "auto.yaml")
    monkeypatch.setattr(cost, "LOG", tmp_path / "costs.jsonl")
    monkeypatch.setattr(external, "SOURCES", dict(external.SOURCES))
    data = k[["iso3", "year", "value"]]
    calls = {"n": 0}

    def llm(prompt):
        calls["n"] += 1
        ind = {"name_ko": "x", "group": "소비트렌드", "source": "external", "flow": "", "transform": "level", "window": 1, "direction": 1}
        if calls["n"] == 1:
            h = {"id": "kpop_new_hyp", "indicators": [dict(ind, id="kpop_new_level", series="kpop_new")],
                 "new_source_needed": "국가별 K-pop 관심도"}
        else:
            h = {"id": "noise_hyp", "indicators": [dict(ind, id="noise_level", series="noise")], "new_source_needed": ""}
        return {"hypotheses": [dict(h, statement="s", rationale="r", group="소비트렌드")]}

    monkeypatch.setattr(external, "catalog", lambda: [{"series": s} for s in ["noise"] + list(external.SOURCES)])
    s = loop.auto(max_rounds=4, patience=1, budget_usd=5.0, fetch=False, llm=llm, client=FakeClient(),
                  scout_fn=lambda *a, **kw: sc.scout(*a, loader=lambda spec, years: data, **kw),
                  log=lambda *a: None, **FAST)
    assert s["rounds"][0]["scouted"] == {"kpop_new": "registered"}
    assert s["rounds"][0]["tested"] == {"auto_kpop_new_hyp": "accepted"}
    assert "개선 정체" in s["stop"] and len(s["rounds"]) == 2
    assert s["adopt"]["written"] and s["spent_usd"] > 0
    assert "데이터 찾아 등록" in loop.report()


def test_scout_hints_strategy_after_repeated_failures(tmp_path):
    class Stubborn(FakeClient):
        def create(self, **kw):
            self.n += 1
            self.last = kw["messages"]
            spec = {"format": "csv", "url": "https://x/y.csv", "wb_indicator": "", "zip_member": "", "sheet": "", "skiprows": 0,
                    "json_path": "", "iso3_col": "iso3", "country_col": "", "year_col": "year", "value_col": "v", "wide_years": False,
                    "filters": []}
            c = [NS(type="tool_use", id=f"t{self.n}", name="try_source", input={"spec": spec})] if self.n <= 5 else \
                [NS(type="tool_use", id="g", name="give_up", input={"reason": "형식 해석 불가", "tried": "x"})]
            return NS(model="claude-opus-5-5", usage=_usage(), stop_reason="tool_use", content=c)
    cl = Stubborn()
    r = sc.scout("zzz", "", {"id": "h"}, list(range(2005, 2025)), cost.Budget(5, path=tmp_path / "c.jsonl"), client=cl,
                 log=lambda *a: None, loader=lambda spec, years: (_ for _ in ()).throw(ValueError("파싱 실패")))
    assert r["status"] == "gave_up"
    hints = [b for m in cl.last if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"] if b.get("type") == "text"]
    assert len(hints) == 1 and "다른 원천" in hints[0]["text"]


def test_selection_windows_never_touch_sealed_period():
    from kfood_scout.agent import loop
    assert max(loop.STARTS) + loop.H <= loop.SEAL_FROM  # 선택용 마지막 창의 정답이 봉인 구간 시작 전에 끝남
