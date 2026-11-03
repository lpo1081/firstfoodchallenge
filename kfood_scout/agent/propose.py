"""가설 제안기(LLM): 지금 모델이 '못 맞힌 나라'와 지난 검증 기록을 보고, 다음에 시험할 지표 가설을 낸다.

Claude API(ANTHROPIC_API_KEY 또는 `ant auth login`)가 있으면 직접 호출하고,
없으면 같은 프롬프트를 파일로 남겨 사람이(또는 Claude Code가) 답을 붙여 넣게 한다.
출력은 JSON 스키마로 강제하고, 쓸 수 없는 원천·변환을 고른 가설은 검증 전에 걸러낸다.
"""
from __future__ import annotations

import json

import numpy as np

from .. import rolling
from ..config import criterion_from_dict
from ..sources import external

MODEL = "claude-opus-5-5"
TRANSFORMS = ["level", "level_log", "per_capita", "cagr", "diff", "per_capita_cagr", "share", "share_diff"]

SCHEMA = {
    "type": "object",
    "properties": {"hypotheses": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"}, "statement": {"type": "string"}, "rationale": {"type": "string"},
            "group": {"type": "string", "enum": ["성장성", "소비트렌드", "수출입"]},
            "new_source_needed": {"type": "string"},
            "indicators": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, "name_ko": {"type": "string"},
                    "group": {"type": "string", "enum": ["성장성", "소비트렌드", "수출입"]},
                    "source": {"type": "string", "enum": ["worldbank", "comtrade", "external"]},
                    "series": {"type": "string"}, "flow": {"type": "string"},
                    "transform": {"type": "string", "enum": TRANSFORMS},
                    "window": {"type": "integer"}, "direction": {"type": "integer"},
                },
                "required": ["id", "name_ko", "group", "source", "series", "flow", "transform", "window", "direction"],
                "additionalProperties": False}},
        },
        "required": ["id", "statement", "rationale", "group", "new_source_needed", "indicators"],
        "additionalProperties": False}}},
    "required": ["hypotheses"],
    "additionalProperties": False,
}

SYSTEM = """너는 K-푸드 수출 유망국을 찾는 분석 에이전트의 '가설 담당'이다.
목표 변수는 't년 이후 3년간 한국→해당국 수출 증가액'(UN Comtrade)이고, 지표는 t년까지의 데이터만 쓴다.
현재 모델이 놓친 나라와 지난 검증 기록을 보고, 표본 밖 예측력을 올릴 수 있는 새 지표 가설을 낸다.
규칙:
- 이미 기각된 가설이나 기존 지표와 사실상 같은 지표는 다시 내지 않는다.
- source=worldbank 이면 series 에 실제 WDI 코드(예: SP.POP.TOTL), flow 는 빈 문자열.
- source=comtrade 이면 flow 는 M(수입), X(수출), KOR_X(한국의 수출) 중 하나, series 는 빈 문자열.
- source=external 이면 series 는 아래 '외부 데이터 목록'의 이름. 목록에 없는 데이터가 꼭 필요하면 series 에 새 이름(영문 소문자_밑줄)을 붙이고
  new_source_needed 에 무엇을 어디서 받을 수 있을지 구체적으로 적는다. 그러면 데이터 담당 에이전트가 웹에서 찾아 등록한 뒤 검증한다.
  국가×연도(2005~2024, 30개국 이상)로 공개된 데이터여야 현실적으로 확보된다.
- 각 가설은 왜 그 지표가 수출 증가를 앞서 보여줄지 한 문단으로 근거를 쓴다. 한국어로 쓴다."""


def misses(panel, countries, base_raw, category, t, k=8) -> list[dict]:
    """최근 창에서 실제 수출 증가 상위인데 모델 순위가 낮았던 나라(=모델이 모르는 무언가가 있는 곳)."""
    crit = criterion_from_dict(base_raw)
    pct, y, raw = rolling.window_matrix(panel, countries, crit, category, t)
    f = rolling.fit(pct.to_numpy(), y.to_numpy(), n=6000)
    score = pct @ f["robust"]
    mr, ar = score.rank(ascending=False), y.rank(ascending=False)
    gap = (mr - ar).sort_values(ascending=False)
    nm = countries.set_index("iso3")["name"].to_dict()
    out = []
    for c in gap.index[:k]:
        out.append({"iso3": c, "name": nm.get(c, c), "actual_rank": int(ar[c]), "model_rank": int(mr[c]), "n": len(y),
                    "indicators_pct": {i: round(float(pct.loc[c, i]), 0) for i in pct.columns}})
    return out


def build_prompt(base_raw, ledger: list[dict], miss: list[dict], n: int = 3, seeds: list[dict] | None = None) -> str:
    ind = [{k: i.get(k) for k in ("id", "name_ko", "group", "source", "series", "flow", "transform")} for i in base_raw["indicators"]]
    hist = [{k: r.get(k) for k in ("hypothesis", "statement", "status", "reason")} for r in ledger[-20:]]
    return "\n\n".join([
        f"현재 지표 {len(ind)}개:\n" + json.dumps(ind, ensure_ascii=False),
        "지난 검증 기록(최근 20건):\n" + json.dumps(hist, ensure_ascii=False),
        "최근 창에서 모델이 놓친 나라(실제 순위 vs 모델 순위, 지표 백분위):\n" + json.dumps(miss, ensure_ascii=False),
        "외부 데이터 목록:\n" + json.dumps(external.catalog(), ensure_ascii=False),
    ] + ([
        "비판 에이전트(레드팀)가 기사에서 찾은, 숫자로 측정 가능해 보이는 반론(가설 후보):\n" + json.dumps(seeds, ensure_ascii=False)
        + "\n이 중 여러 나라에 공통으로 적용될 수 있는 것은 지표 가설로 바꿔 시험해 볼 가치가 있다(direction 은 보통 -1). "
          "가설 id 는 critic_ 으로 시작하게 하라."
    ] if seeds else []) + [
        f"다음에 시험할 가설을 최대 {n}개 내라.",
    ])


def call_llm(prompt: str, budget=None) -> dict:
    import anthropic  # pip install anthropic

    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM, messages=[{"role": "user", "content": prompt}],
    )
    if budget is not None:
        budget.record("propose", resp)
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"LLM 거절: {resp.stop_details}")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def validate(h: dict) -> tuple[bool, str]:
    names = {c["series"] for c in external.catalog()}
    for i in h["indicators"]:
        if i["source"] == "external" and i["series"] not in names:
            return False, f"미등록 외부 원천 {i['series']} (new_source_needed: {h.get('new_source_needed')})"
        if i["source"] == "comtrade" and i["flow"] not in ("M", "X", "KOR_X"):
            return False, f"comtrade flow {i['flow']} 불가"
        if i["direction"] not in (1, -1):
            return False, "direction 은 1 또는 -1"
    return True, ""


def clean(h: dict) -> dict:
    """스키마의 빈 문자열을 지표 정의 형식으로 정리."""
    out = dict(h, proposed_by=f"llm:{MODEL}")
    out["indicators"] = []
    for i in h["indicators"]:
        i = {k: v for k, v in i.items() if v != ""}
        out["indicators"].append(i)
    return out


def propose(panel, countries, base_raw, category, ledger, t=None, n=3, llm=None) -> tuple[list[dict], list[dict], str]:
    """반환: (검증 가능한 가설, 걸러진 가설과 이유, 프롬프트). llm 은 테스트용 대체 함수."""
    t = t or max(base_raw.get("_starts", [2018]))
    from .critic import load_seeds  # 레드팀 반론 → 가설 씨앗(없으면 빈 목록)

    prompt = build_prompt(base_raw, ledger, misses(panel, countries, base_raw, category, t), n, load_seeds())
    js = (llm or call_llm)(prompt)
    ok, dropped = [], []
    for h in js.get("hypotheses", []):
        h = clean(h)
        good, why = validate(h)
        (ok if good else dropped).append(h if good else {**h, "status": "data_needed", "reason": why})
    return ok, dropped, prompt
