"""비판 에이전트: 통계 모델이 뽑은 후보국을 '뽑으면 안 되는 이유' 쪽에서 공격한다.

흐름(국가마다):
  Claude 가 최근 기사·규제·정치 뉴스를 웹 검색(web_search, 횟수 상한) → submit_critique 로 반론 카드 제출
  → 아래의 고정 코드가 판정: 실제 검색 결과에 나온 주소만 근거로 인정, 오래된 기사 제외,
     '치명' 은 서로 다른 출처 2곳 이상일 때만 인정, 반론별 대응 조건으로 진출/조건부 진출/배제 결정(LLM 은 판정하지 않음)
  → 숫자로 바꿀 수 있는 반론은 '가설 씨앗'으로 저장 → 다음 `agent auto/loop` 때 가설 담당이 받아 통계로 검증

설정은 config/critic.yaml(후보·분야·규칙). 결과는 outputs/agent/critic/<ISO3>.json(캐시) 과 board.md(장부).
비용은 Budget 상한을 넘기기 전에 멈추고, 이미 본 나라는 cache_days 동안 다시 검색하지 않는다.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from ..config import CONFIG, ROOT
from .cost import Budget

MODEL = "claude-opus-5-5"
OUT = ROOT / "outputs" / "agent" / "critic"
SEV = ["낮음", "중간", "치명"]
PER_COUNTRY_RESERVE = 0.15  # 한 나라 검색에 드는 대략적 비용(USD). 남은 예산이 이보다 적으면 시작하지 않는다.


def load_cfg(path: Path | None = None) -> dict:
    return yaml.safe_load((path or CONFIG / "critic.yaml").read_text())


# ---------- 후보 국가 ----------

def candidates(cfg: dict, ranking: str | None = None, countries: str | None = None, top: int | None = None) -> list[dict]:
    """우선순위: --countries(ISO3 쉼표) > --ranking(json/csv, 순서대로, iso3 열) > config 의 candidates."""
    known = {c["iso3"]: c for c in cfg["candidates"]}
    names = {}
    if countries:
        isos = [x.strip().upper() for x in countries.split(",") if x.strip()]
    elif ranking:
        isos, names = _ranking_isos(Path(ranking))
    else:
        isos = [c["iso3"] for c in cfg["candidates"]]
    # 설정에 없는 나라는 순위 파일의 이름(name)을 검색어로 쓴다. 그것도 없으면 ISO3.
    out = [dict(known.get(i, {"iso3": i, "name_ko": names.get(i, i), "name_en": names.get(i, i)}), rank=n + 1)
           for n, i in enumerate(isos)]
    return out[:top] if top else out


def _ranking_isos(p: Path) -> tuple[list[str], dict[str, str]]:
    """순위 파일에서 ISO3 순서와 (있으면) 나라 이름을 읽는다. iso3 열/키만 있으면 형식이 달라도 된다."""
    if p.suffix == ".csv" or p.suffix == ".psv":
        with p.open(encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f, delimiter="|" if p.suffix == ".psv" else ",") if r.get("iso3")]
    else:
        js = json.loads(p.read_text())
        if isinstance(js, dict):
            for k in ("ranking", "top", "candidates", "countries"):
                if isinstance(js.get(k), list):
                    js = js[k]
                    break
        rows = [{"iso3": x} if isinstance(x, str) else x for x in js]
    isos = [r["iso3"].strip().upper() for r in rows]
    names = {r["iso3"].strip().upper(): r["name"] for r in rows if r.get("name")}
    return isos, names


# ---------- Claude 에게 주는 지시와 제출 양식 ----------

def system_prompt(cfg: dict) -> str:
    return f"""너는 K-푸드 수출 유망국 분석팀의 '반대 담당(레드팀)'이다.
통계 모델이 어떤 나라를 {cfg['product']} 수출 유망국으로 뽑았다. 네 일은 그 결론을 공격하는 것이다:
"이 나라를 우선 진출국으로 뽑으면 안 되는 이유"를 최근 {cfg['lookback_years']}년 안의 기사·정부 발표·규제 문서에서 찾아라.
분야: {', '.join(cfg['categories'])}.
규칙:
- 반드시 web_search 로 찾은 기사만 근거로 쓴다. 근거 url 은 검색 결과에 나온 주소를 그대로 적는다. 기억에 의존한 주장은 버린다.
- 심각도: 치명 = 진출 자체를 막거나 2~3년 안에 큰 손실이 날 일(수입 금지, 내전·쿠데타, 제재, 과자류 관세 급등 등).
  중간 = 비용·속도에 실질적 영향(인증 지연, 라벨 규제, 환율 급락, 강한 현지 경쟁). 낮음 = 참고.
- 통계 모델은 이미 인구·소득·수입시장 규모·한류 관심도·한국 수출 추세를 반영했다. 그 숫자가 놓치는 것을 찾아라.
- 반론이 숫자로 측정 가능하면(국가×연도 공개 데이터가 있을 법하면) quantifiable=true 로 하고 indicator_idea 에 어떤 지표·원천인지 적는다.
- 공정하게: 반론을 반박하는 사실(진출을 지지하는 근거)도 support 에 따로 적는다.
- 반론마다 condition 에 "그래도 진출한다면 무엇을 해야 하는가"를 실행 가능한 한 문장으로 적는다(품목·채널·인증·가격·시점 등 구체적으로).
  그 조건을 지켜도 감당이 안 되면(수입 금지, 전쟁 등) mitigable=false.
- go_line 에는 "진출한다/하지 않는다"로 시작하는 실무자용 결론 한 문장을 쓴다.
- 검색은 국가당 {cfg['max_searches']}회 안에서 끝내고 submit_critique 를 한 번 호출해 마친다. 한국어로 간결하게."""


EVID = {"type": "array", "items": {"type": "object", "properties": {
    "url": {"type": "string"}, "title": {"type": "string"}, "publisher": {"type": "string"},
    "date": {"type": "string", "description": "YYYY-MM 또는 YYYY-MM-DD, 모르면 빈 문자열"}},
    "required": ["url", "title", "publisher", "date"], "additionalProperties": False}}


def tools(cfg: dict) -> list[dict]:
    return [
        # 기본형 검색 도구를 쓴다: 검색 결과가 web_search_tool_result 블록으로 그대로 와야 '실제로 검색된 주소'를 대조할 수 있다.
        {"type": "web_search_20250305", "name": "web_search", "max_uses": cfg["max_searches"]},
        {"name": "submit_critique", "strict": True,
         "description": "이 나라에 대한 반론 카드를 제출하고 끝낸다.",
         "input_schema": {"type": "object", "properties": {
             "objections": {"type": "array", "items": {"type": "object", "properties": {
                 "claim": {"type": "string", "description": "반론 한 문장"},
                 "category": {"type": "string", "enum": cfg["categories"]},
                 "severity": {"type": "string", "enum": SEV},
                 "evidence": EVID,
                 "quantifiable": {"type": "boolean"},
                 "indicator_idea": {"type": "string", "description": "측정 지표·원천 아이디어, 없으면 빈 문자열"},
                 "condition": {"type": "string", "description": "그래도 진출한다면 해야 할 일(실행 조건·전술) 한 문장"},
                 "mitigable": {"type": "boolean", "description": "condition 을 지키면 감당 가능한가"}},
                 "required": ["claim", "category", "severity", "evidence", "quantifiable", "indicator_idea",
                              "condition", "mitigable"],
                 "additionalProperties": False}},
             "support": {"type": "array", "items": {"type": "object", "properties": {
                 "claim": {"type": "string"}, "evidence": EVID},
                 "required": ["claim", "evidence"], "additionalProperties": False}},
             "summary": {"type": "string", "description": "레드팀 총평 2문장"},
             "go_line": {"type": "string", "description": "'진출한다' 또는 '진출하지 않는다'로 시작하는 결론 한 문장"}},
             "required": ["objections", "support", "summary", "go_line"], "additionalProperties": False}},
    ]


def user_prompt(c: dict, cfg: dict, today: dt.date) -> str:
    return (f"대상 국가: {c['name_ko']} ({c['name_en']}, {c['iso3']}), 모델 순위 {c.get('rank', '?')}위.\n"
            f"오늘 날짜: {today.isoformat()}. {today.year - cfg['lookback_years']}년 이후 기사만 근거로 인정된다.\n"
            f"이 나라에 {cfg['product']}를 수출 확대하면 안 되는 이유를 찾아 submit_critique 로 제출하라.")


# ---------- 판정(고정 코드) ----------

def _norm(u: str) -> str:
    u = (u or "").strip()
    return u[:-1] if u.endswith("/") else u


def _domain(u: str) -> str:
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _date(s: str) -> dt.date | None:
    m = re.search(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", s or "")
    if not m:
        m2 = re.search(r"(20\d{2})", s or "")
        return dt.date(int(m2.group(1)), 6, 30) if m2 else None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    except ValueError:
        return None


def collect_sources(content) -> dict[str, dict]:
    """응답의 web_search 결과 블록에서 실제로 검색된 주소들을 모은다(=인정 가능한 근거의 범위)."""
    seen = {}
    for b in content:
        t = getattr(b, "type", "")
        if t.endswith("tool_result") and t != "web_search_tool_result":  # 코드 실행 등으로 걸러진 결과 안의 주소도 인정
            out = getattr(getattr(b, "content", None), "stdout", "") or ""
            for u in re.findall(r"https?://[^\s\"'<>)\]]+", out):
                seen.setdefault(_norm(u), {"title": "", "page_age": ""})
            continue
        if t != "web_search_tool_result":
            continue
        items = getattr(b, "content", None)
        if not isinstance(items, list):  # 검색 오류면 리스트가 아닌 객체
            continue
        for r in items:
            url = _norm(getattr(r, "url", ""))
            if url:
                seen[url] = {"title": getattr(r, "title", ""), "page_age": getattr(r, "page_age", "") or ""}
    return seen


def _check_evidence(evs: list[dict], seen: dict, cutoff: dt.date) -> tuple[list[dict], list[str]]:
    ok, why = [], []
    for e in evs:
        u = _norm(e.get("url", ""))
        if u not in seen:
            why.append(f"검색 결과에 없는 주소: {u[:80]}")
            continue
        d = _date(e.get("date", "")) or _date(seen[u].get("page_age", ""))
        if d and d < cutoff:
            why.append(f"오래된 기사({d.isoformat()}): {u[:80]}")
            continue
        ok.append(dict(e, url=u, date=d.isoformat() if d else "날짜 미상"))
    return ok, why


def judge(card: dict, seen: dict, cfg: dict, today: dt.date) -> dict:
    """LLM 이 낸 카드를 규칙으로 걸러 판정한다. 반환 카드에 kept/dropped/verdict 가 붙는다."""
    rules = cfg["rules"]
    cutoff = dt.date(today.year - cfg["lookback_years"], today.month, min(today.day, 28))
    kept, dropped = [], []
    for o in card.get("objections", []):
        evs, why = _check_evidence(o.get("evidence", []), seen, cutoff)
        if not evs:
            dropped.append({**o, "dropped_because": "; ".join(why) or "근거 없음"})
            continue
        o = dict(o, evidence=evs, llm_severity=o["severity"])
        doms = {_domain(e["url"]) for e in evs}
        if o["severity"] == "치명" and len(doms) < rules["fatal_min_domains"]:
            o["severity"] = "중간"
            o["note"] = f"치명 주장이지만 출처 {len(doms)}곳뿐이라 중간으로 낮춤"
        kept.append(o)
    support = []
    for s in card.get("support", []):
        evs, _ = _check_evidence(s.get("evidence", []), seen, cutoff)
        if evs:
            support.append(dict(s, evidence=evs))
    out = {**{k: v for k, v in card.items() if k not in ("objections", "support")},
           "objections": kept, "dropped": dropped, "support": support, "searched_urls": len(seen)}
    return decide(out, rules)


VERDICTS = ["진출", "조건부 진출", "배제"]


def decide(card: dict, rules: dict) -> dict:
    """반론 목록 → 진출 결정. 감당 불가한 치명 반론이 있으면 배제, 조건이 필요한 반론이 있으면 조건부 진출(조건 = 그 반론들의
    condition, 심각한 것부터 max_conditions 개), 아니면 진출. LLM 이 아니라 이 규칙이 결정한다."""
    kept = card.get("objections", [])
    n = {s: sum(1 for o in kept if o["severity"] == s) for s in SEV}
    blockers = [o for o in kept if o["severity"] == "치명" and o.get("mitigable") is False]
    need = sorted([o for o in kept if o["severity"] in rules["conditional_if"]], key=lambda o: -SEV.index(o["severity"]))
    if len(blockers) >= rules["exclude_if_unmitigable_fatal"]:
        verdict, conds = "배제", [o["claim"] for o in blockers]
    elif need:
        verdict = "조건부 진출"
        conds = [o.get("condition") or f"(조건 미작성: agent decide 로 채움) {o['claim'][:40]}" for o in need]
    else:
        verdict, conds = "진출", []
    return dict(card, counts=n, verdict=verdict, conditions=conds[:rules["max_conditions"]],
                more_conditions=max(0, len(conds) - rules["max_conditions"]))


# ---------- 실행 ----------

def _cached(iso3: str, days: int, today: dt.date) -> dict | None:
    p = OUT / f"{iso3}.json"
    if not p.exists():
        return None
    js = json.loads(p.read_text())
    d = _date(js.get("checked", ""))
    return js if d and (today - d).days <= days else None


def critique_country(c: dict, cfg: dict, budget: Budget, client, today: dt.date, max_steps: int = 4, log=print) -> dict:
    messages = [{"role": "user", "content": user_prompt(c, cfg, today)}]
    seen, queries = {}, []
    for _ in range(max_steps):
        resp = client.beta.messages.create(
            model=MODEL, max_tokens=16000, system=system_prompt(cfg), tools=tools(cfg), messages=messages,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "medium"},
        )
        budget.record(f"critic:{c['iso3']}", resp)
        seen.update(collect_sources(resp.content))
        for b in resp.content:
            if getattr(b, "type", "") == "server_tool_use":
                q = (getattr(b, "input", {}) or {}).get("query", "")
                queries.append(q)
                log(f"[critic:{c['iso3']}] 검색: {q}")
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "refusal":
            return {"status": "refusal", "queries": queries}
        if resp.stop_reason == "pause_turn":
            continue
        sub = next((b for b in resp.content if getattr(b, "type", "") == "tool_use" and b.name == "submit_critique"), None)
        if sub:
            card = sub.input if isinstance(sub.input, dict) else json.loads(sub.input)
            return {"status": "ok", "card": card, "seen": seen, "queries": queries}
        messages.append({"role": "user", "content": "검색은 충분하다. 지금까지 찾은 기사로 submit_critique 를 호출해 마쳐라."})
    return {"status": "steps", "queries": queries}


def run(ranking=None, countries=None, top=None, budget_usd=1.0, refresh=False, client=None, cfg=None,
        today: dt.date | None = None, log=print) -> dict:
    cfg = cfg or load_cfg()
    today = today or dt.date.today()
    OUT.mkdir(parents=True, exist_ok=True)
    budget = Budget(budget_usd)
    cands = candidates(cfg, ranking, countries, top)
    done, skipped = [], []
    for c in cands:
        if not refresh and (hit := _cached(c["iso3"], cfg["cache_days"], today)):
            hit = decide(hit, cfg["rules"])  # 규칙이 바뀌었으면 캐시 카드도 새 규칙으로 다시 판정(무료)
            log(f"[critic:{c['iso3']}] {hit['checked']} 결과 재사용(무료): {hit['verdict']}")
            done.append(dict(hit, rank=c.get("rank")))
            continue
        if budget.left < PER_COUNTRY_RESERVE:
            skipped.append(c["iso3"])
            continue
        if client is None:
            import anthropic  # pip install anthropic

            client = anthropic.Anthropic()
        r = critique_country(c, cfg, budget, client, today, log=log)
        if r["status"] != "ok":
            log(f"[critic:{c['iso3']}] 실패: {r['status']}")
            skipped.append(c["iso3"])
            continue
        card = judge(r["card"], r["seen"], cfg, today)
        card = {"iso3": c["iso3"], "name_ko": c["name_ko"], "rank": c.get("rank"), "checked": today.isoformat(),
                "model": MODEL, "queries": r["queries"], **card}
        (OUT / f"{c['iso3']}.json").write_text(json.dumps(card, ensure_ascii=False, indent=1))
        log(f"[critic:{c['iso3']}] {card['verdict']} (치명 {card['counts']['치명']}, 중간 {card['counts']['중간']}, "
            f"낮음 {card['counts']['낮음']}, 근거 부족으로 버린 반론 {len(card['dropped'])}) 누적 ${budget.spent:.2f}")
        done.append(card)
    if skipped:
        log(f"[critic] 예산·오류로 못 본 나라: {skipped} → 같은 명령을 다시 실행하면 이어서 봅니다(본 나라는 무료 재사용).")
    seeds = write_seeds(done)
    summary = {"checked": [d["iso3"] for d in done], "skipped": skipped, "spent_usd": round(budget.spent, 3),
               "verdicts": {d["iso3"]: d["verdict"] for d in done}, "seeds": len(seeds)}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


# ---------- 이미 받은 반론 카드에 진출 조건 채우기(검색 없음, 저비용) ----------

COND_SCHEMA = {"type": "object", "properties": {
    "items": {"type": "array", "items": {"type": "object", "properties": {
        "index": {"type": "integer"}, "condition": {"type": "string"}, "mitigable": {"type": "boolean"}},
        "required": ["index", "condition", "mitigable"], "additionalProperties": False}},
    "go_line": {"type": "string"}},
    "required": ["items", "go_line"], "additionalProperties": False}


def fill_conditions(card: dict, cfg: dict, budget: Budget, client) -> dict:
    """condition/mitigable 이 없는 옛 카드에 한 번의 호출(검색 없음)로 진출 조건을 채운다."""
    objs = [{"index": i, "claim": o["claim"], "category": o["category"], "severity": o["severity"]}
            for i, o in enumerate(card["objections"])]
    prompt = (f"나라: {card['name_ko']} ({card['iso3']}), 품목: {cfg['product']}.\n"
              f"레드팀이 기사로 확인한 반론:\n{json.dumps(objs, ensure_ascii=False)}\n"
              f"반박 근거: {json.dumps([s['claim'] for s in card.get('support', [])], ensure_ascii=False)}\n\n"
              "각 반론에 대해 '그래도 진출한다면 해야 할 일'(품목·채널·인증·가격·시점 등 구체적 실행 조건) 한 문장을 condition 에, "
              "그 조건을 지켜도 감당이 안 되면 mitigable=false 로 적어라. go_line 은 '진출한다' 또는 '진출하지 않는다'로 시작하는 "
              "실무자용 결론 한 문장. 한국어로.")
    resp = client.messages.create(
        model=MODEL, max_tokens=4000, messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": COND_SCHEMA}},
    )
    budget.record(f"decide:{card['iso3']}", resp)
    if resp.stop_reason == "refusal":
        return card
    js = json.loads(next(b.text for b in resp.content if b.type == "text"))
    objs = [dict(o) for o in card["objections"]]
    for it in js["items"]:
        if 0 <= it["index"] < len(objs):
            objs[it["index"]].update(condition=it["condition"], mitigable=it["mitigable"])
    return dict(card, objections=objs, go_line=js["go_line"])


def backfill(budget_usd: float = 0.3, client=None, cfg=None, log=print) -> dict:
    """마지막 실행에서 본 나라 중 조건이 비어 있는 카드만 채우고, 새 규칙으로 다시 판정한다."""
    cfg = cfg or load_cfg()
    budget = Budget(budget_usd)
    out = {}
    for card in load_cards():
        if any("condition" not in o for o in card["objections"]) and budget.left >= 0.05:
            if client is None:
                import anthropic  # pip install anthropic

                client = anthropic.Anthropic()
            card = fill_conditions(card, cfg, budget, client)
        card = decide(card, cfg["rules"])
        (OUT / f"{card['iso3']}.json").write_text(json.dumps(card, ensure_ascii=False, indent=1))
        out[card["iso3"]] = card["verdict"]
        log(f"[decide:{card['iso3']}] {card['verdict']}: " + " / ".join(card["conditions"]))
    sp = OUT / "summary.json"
    if sp.exists():
        summ = json.loads(sp.read_text())
        summ["verdicts"] = {**summ.get("verdicts", {}), **out}
        sp.write_text(json.dumps(summ, ensure_ascii=False, indent=1))
    return {"verdicts": out, "spent_usd": round(budget.spent, 3)}


# ---------- 반론 → 가설 씨앗 ----------

SEEDS = OUT / "seeds.json"


def write_seeds(cards: list[dict]) -> list[dict]:
    seeds = [{"iso3": c["iso3"], "claim": o["claim"], "category": o["category"], "severity": o["severity"],
              "indicator_idea": o["indicator_idea"]}
             for c in cards for o in c.get("objections", []) if o.get("quantifiable") and o.get("indicator_idea")]
    OUT.mkdir(parents=True, exist_ok=True)
    SEEDS.write_text(json.dumps(seeds, ensure_ascii=False, indent=1))
    return seeds


def load_seeds(k: int = 12) -> list[dict]:
    """가설 담당 프롬프트에 넣을 반론 씨앗(심각한 것부터)."""
    if not SEEDS.exists():
        return []
    s = json.loads(SEEDS.read_text())
    return sorted(s, key=lambda x: -SEV.index(x.get("severity", "낮음")))[:k]


def load_cards() -> list[dict]:
    """마지막 실행(summary.json)에서 본 나라들의 카드, 그 실행의 순위 순서대로."""
    sp = OUT / "summary.json"
    if not sp.exists():
        return []
    order = json.loads(sp.read_text())["checked"]
    return [json.loads((OUT / f"{i}.json").read_text()) | {"rank": n + 1} for n, i in enumerate(order)
            if (OUT / f"{i}.json").exists()]
