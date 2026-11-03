"""데이터 탐색 에이전트: 가설에 필요한 데이터가 없을 때, 웹에서 원천을 찾아 '수집 명세'를 만들고 시험해 등록한다.

흐름(Claude 가 도구를 골라 가며 스스로 진행):
  web_search / web_fetch (Anthropic 서버에서 실행) 로 국가×연도 데이터를 내려받을 수 있는 주소를 찾는다
  → try_source: 수집 명세(주소·형식·열 이름)를 이 컴퓨터의 정해진 수집기로 내려받아 검사 결과를 돌려받는다
  → 실패하면 원인(열 이름 오류, 국가 수 부족, 값 퇴화 등)을 보고 명세를 고치거나 다른 원천을 찾는다
  → register_source: 검사를 통과한 명세를 등록(config/sources/auto_sources.yaml) / give_up: 포기 사유 기록

안전 설계: Claude 가 짠 코드를 실행하지 않는다. Claude 는 '어디서 무엇을 받을지'만 정하고(명세),
내려받기·해석은 아래의 고정된 코드(load_spec)가 한다. 받을 수 있는 것은 http(s) 공개 파일(CSV·엑셀·JSON)과
World Bank 지표 코드뿐이고, 파일 크기·시간에 상한이 있다. 비용은 Budget 으로 상한을 둔다.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import zipfile

import pandas as pd
import yaml

from ..config import CONFIG
from ..sources import external
from .cost import Budget

MODEL = "claude-opus-5-5"
AUTO_SOURCES = CONFIG / "sources" / "auto_sources.yaml"
MIN_COUNTRIES, MIN_YEARS, MIN_UNIQUE = 30, 8, 5
MAX_BYTES, TIMEOUT = 60_000_000, 120
STRATEGY = ("같은 원천에서 4번 실패했다. 같은 주소를 더 고치지 말고, World Bank 지표 코드나 Our World in Data 처럼 "
            "형식이 단순한 다른 원천, 또는 의미가 가까운 대리지표로 바꿔라. 그것도 어렵다면 give_up 하라.")

SYSTEM = """너는 K-푸드 수출 유망국 분석 에이전트의 '데이터 담당'이다.
가설을 검증하려면 특정 지표의 국가×연도 데이터가 필요한데 아직 없다. 공신력 있는 공개 원천을 찾아
내려받을 수 있는 파일 주소와 열 이름을 '수집 명세'로 만들고, try_source 로 시험해 검사를 통과하면 register_source 로 등록하라.

수집 명세로 받을 수 있는 것:
- format=worldbank: World Bank WDI 지표 코드(wb_indicator)만 주면 된다.
- format=csv / xlsx / json: 로그인 없이 받을 수 있는 공개 파일 주소(url). zip 안의 파일이면 zip_member 를 쓴다.
  국가 열(iso3_col 또는 country_col), 연도 열(year_col), 값 열(value_col)을 정확히 적는다.
  연도가 열 이름으로 펼쳐진 표(1990, 1991, ... 열)면 wide_years=true 로 하고 year_col·value_col 은 빈 문자열.
  다른 지표가 섞인 긴 표면 filters 로 행을 고른다(예: [{"col":"Indicator","value":"Mobile subscriptions"}]).
- Our World in Data 그래프는 https://ourworldindata.org/grapher/<이름>.csv 형태로 바로 받을 수 있다(열: Entity, Code, Year, 값).
World Bank·OECD·UN·IMF·FAO·ILO·ITU·UNESCO·Our World in Data 같은 공공·학술 원천을 우선한다.
원래 필요한 지표가 없으면 의미가 가까운 대리지표를 써도 되지만, register 할 때 notes 에 무엇을 대신했는지 적는다.
검사 기준: 국가 30개 이상, 국가 30개 이상인 연도 8개 이상(2005~2024 중), 연도별 서로 다른 값 5개 이상.
검사에 실패하면 결과(열 목록, 표본 행, 문제)를 보고 명세를 고쳐 다시 시도하고, 여러 원천이 다 안 되면 give_up 으로 이유를 남긴다.
도구를 쓰는 데 집중하고, 설명은 짧게 한국어로."""

SPEC = {
    "type": "object",
    "properties": {
        "format": {"type": "string", "enum": ["worldbank", "csv", "xlsx", "json"]},
        "url": {"type": "string"}, "wb_indicator": {"type": "string"}, "zip_member": {"type": "string"},
        "sheet": {"type": "string"}, "skiprows": {"type": "integer"}, "json_path": {"type": "string"},
        "iso3_col": {"type": "string"}, "country_col": {"type": "string"},
        "year_col": {"type": "string"}, "value_col": {"type": "string"}, "wide_years": {"type": "boolean"},
        "filters": {"type": "array", "items": {"type": "object", "properties": {"col": {"type": "string"}, "value": {"type": "string"}},
                                                "required": ["col", "value"], "additionalProperties": False}},
    },
    "required": ["format", "url", "wb_indicator", "zip_member", "sheet", "skiprows", "json_path", "iso3_col", "country_col",
                 "year_col", "value_col", "wide_years", "filters"],
    "additionalProperties": False,
}

TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 10, "max_content_tokens": 20000},
    {"name": "try_source", "strict": True,
     "description": "수집 명세대로 데이터를 내려받아 검사하고 결과(국가 수, 연도 수, 값 퇴화 여부, 열 목록, 표본 행, 오류)를 돌려준다. "
                    "쓰지 않는 칸은 빈 문자열/0/false/빈 배열로 둔다.",
     "input_schema": {"type": "object", "properties": {"spec": SPEC}, "required": ["spec"], "additionalProperties": False}},
    {"name": "register_source", "strict": True,
     "description": "마지막으로 try_source 를 통과한 명세를 원천으로 등록한다. 통과하지 못했으면 거절된다.",
     "input_schema": {"type": "object", "properties": {
         "desc": {"type": "string", "description": "무슨 데이터인지 한 줄(한국어)"},
         "publisher": {"type": "string"}, "notes": {"type": "string", "description": "대리지표를 썼다면 무엇을 대신했는지, 한계"}},
         "required": ["desc", "publisher", "notes"], "additionalProperties": False}},
    {"name": "give_up", "strict": True, "description": "적절한 원천을 찾지 못했을 때 이유를 남기고 끝낸다.",
     "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}, "tried": {"type": "string"}},
                      "required": ["reason", "tried"], "additionalProperties": False}},
]


# ---------- 고정 수집기: 명세 → 국가×연도 표 (Claude 의 코드를 실행하지 않음) ----------

def _download(url: str) -> bytes:
    import requests

    if not url.startswith(("https://", "http://")):
        raise ValueError("http(s) 주소만 받을 수 있음")
    with requests.get(url, timeout=TIMEOUT, stream=True, headers={"User-Agent": "kfood-scout/1.0"}) as r:
        r.raise_for_status()
        buf = io.BytesIO()
        for chunk in r.iter_content(1 << 16):
            buf.write(chunk)
            if buf.tell() > MAX_BYTES:
                raise ValueError(f"파일이 {MAX_BYTES // 1_000_000}MB 를 넘음")
    return buf.getvalue()


def _wb(code: str, years: list[int]) -> pd.DataFrame:
    from ..sources.base import cached_get_json

    js = cached_get_json(f"https://api.worldbank.org/v2/country/all/indicator/{code}",
                         {"format": "json", "per_page": 20000, "date": f"{min(years)}:{max(years)}"})
    if not isinstance(js, list) or len(js) < 2 or not js[1]:
        raise ValueError(f"World Bank 지표 {code} 데이터 없음: {str(js)[:300]}")
    return pd.DataFrame([{"iso3": r["countryiso3code"], "year": r["date"], "value": r["value"]} for r in js[1]])


def load_spec(spec: dict, years: list[int]) -> pd.DataFrame:
    """명세대로 내려받아 원본 표(열 이름 그대로)를 돌려준다."""
    if spec["format"] == "worldbank":
        return _wb(spec["wb_indicator"], years)
    raw = _download(spec["url"])
    if spec.get("zip_member"):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            raw = z.read(spec["zip_member"])
    skip = spec.get("skiprows") or 0
    if spec["format"] == "csv":
        return pd.read_csv(io.BytesIO(raw), skiprows=skip, encoding_errors="ignore", low_memory=False)
    if spec["format"] == "xlsx":
        return pd.read_excel(io.BytesIO(raw), sheet_name=spec.get("sheet") or 0, skiprows=skip)
    js = json.loads(raw)
    for k in [k for k in (spec.get("json_path") or "").split(".") if k]:
        js = js[int(k)] if isinstance(js, list) else js[k]
    return pd.json_normalize(js)


def to_panel(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """원본 표 → iso3/year/value. 열 이름이 틀리면 열 목록을 담은 오류를 낸다."""
    if spec["format"] == "worldbank":
        out = df
    else:
        for f in spec.get("filters") or []:
            if f["col"] not in df.columns:
                raise KeyError(f"필터 열 '{f['col']}' 없음")
            df = df[df[f["col"]].astype(str) == f["value"]]
        keys = [c for c in (spec.get("iso3_col"), spec.get("country_col")) if c]
        if not keys:
            raise KeyError("iso3_col 또는 country_col 을 적어야 함")
        miss = [c for c in keys + ([] if spec.get("wide_years") else [spec["year_col"], spec["value_col"]]) if c not in df.columns]
        if miss:
            raise KeyError(f"열 {miss} 없음")
        if spec.get("wide_years"):
            ycols = [c for c in df.columns if str(c).strip()[:4].isdigit() and len(str(c).strip()) in (4, 6)]
            df = df.melt(id_vars=keys, value_vars=ycols, var_name="year", value_name="value")
            df["year"] = df["year"].astype(str).str[:4]
        else:
            df = df.rename(columns={spec["year_col"]: "year", spec["value_col"]: "value"})
        out = df.rename(columns={spec.get("iso3_col") or "_": "iso3", spec.get("country_col") or "_": "country"})
    if "iso3" not in out.columns or out["iso3"].isna().all():
        m = external._name_to_iso3()
        out["iso3"] = out["country"].astype(str).str.lower().str.strip().map(m)
    out = out.assign(year=pd.to_numeric(out["year"], errors="coerce"), value=pd.to_numeric(out["value"], errors="coerce"))
    out = out.dropna(subset=["iso3", "year", "value"])
    out["iso3"] = out["iso3"].astype(str).str.upper()
    out = out[out["iso3"].str.fullmatch(r"[A-Z][A-Z0-9]{2}") & ~out["iso3"].str.startswith(("OWID", "WLD"))]
    return out.astype({"year": int}).groupby(["iso3", "year"], as_index=False)["value"].mean()


def check(spec: dict, years: list[int], loader=load_spec) -> dict:
    """검사 결과. ok=True 여야 등록할 수 있다. _df 는 통과 시 등록할 표."""
    try:
        raw = loader(spec, years)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "problems": [f"내려받기 실패: {type(e).__name__}: {str(e)[:600]}"]}
    try:
        d = to_panel(raw, spec)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "problems": [f"해석 실패: {e}"], "columns": [str(c) for c in raw.columns][:80],
                "head": raw.head(4).astype(str).to_dict("records")}
    d = d[d.year.isin(years)]
    per_year = d.groupby("year")["iso3"].nunique()
    good_years = per_year[per_year >= MIN_COUNTRIES]
    uniq = d.groupby("year")["value"].nunique()
    problems = []
    if d.iso3.nunique() < MIN_COUNTRIES:
        problems.append(f"국가 {d.iso3.nunique()}개 < {MIN_COUNTRIES} (국가명 매핑 실패라면 ISO3 코드 열을 쓰는 원천을 찾을 것)")
    if len(good_years) < MIN_YEARS:
        problems.append(f"국가 {MIN_COUNTRIES}개 이상인 연도 {len(good_years)}개 < {MIN_YEARS}")
    if len(uniq) and uniq.median() < MIN_UNIQUE:
        problems.append(f"연도별 고유값 중앙값 {uniq.median():.0f} < {MIN_UNIQUE} (값이 퇴화)")
    return {"ok": not problems, "problems": problems, "rows": len(d), "countries": int(d.iso3.nunique()),
            "countries_per_year": {int(k): int(v) for k, v in per_year.items()},
            "value_range": [float(d.value.min()), float(d.value.max())] if len(d) else None,
            "sample": d.sample(min(6, len(d)), random_state=0).to_dict("records") if len(d) else [], "_df": d}


def _register(series: str, spec: dict, d: pd.DataFrame, meta: dict, hyp_id: str) -> dict:
    external.RAW.mkdir(parents=True, exist_ok=True)
    d[["iso3", "year", "value"]].to_csv(external.RAW / f"auto_{series}.csv", index=False)
    reg = (yaml.safe_load(AUTO_SOURCES.read_text()) if AUTO_SOURCES.exists() else None) or {}
    reg[series] = {"kind": "file", "file": f"auto_{series}.csv", "desc": meta["desc"],
                   "how": f"{meta['publisher']} {spec.get('url') or 'WB:' + spec.get('wb_indicator', '')}",
                   "notes": meta["notes"], "spec": {k: v for k, v in spec.items() if v not in ("", 0, False, [], None)},
                   "by": f"scout:{MODEL}", "for": hyp_id, "created": dt.date.today().isoformat()}
    AUTO_SOURCES.parent.mkdir(parents=True, exist_ok=True)
    AUTO_SOURCES.write_text(yaml.safe_dump(reg, allow_unicode=True, sort_keys=False))
    external.load_auto_sources()
    return reg[series]


def _brief(chk: dict) -> str:
    return json.dumps({k: v for k, v in chk.items() if k != "_df"}, ensure_ascii=False, default=str)[:4000]


def scout(series: str, need: str, hyp: dict, years: list[int], budget: Budget, client=None,
          max_steps: int = 14, log=print, loader=load_spec) -> dict:
    """series 이름으로 등록할 데이터를 찾는다. 반환 status: registered | gave_up | budget | steps | refusal."""
    if client is None:
        import anthropic  # pip install anthropic

        client = anthropic.Anthropic()
    ind = [i for i in hyp.get("indicators", []) if i.get("series") == series]
    prompt = (f"필요한 데이터(series 이름: {series}):\n{need or '(설명 없음)'}\n\n"
              f"이 데이터를 쓰는 가설: {hyp.get('statement', '')}\n근거: {hyp.get('rationale', '')}\n"
              f"지표 정의: {json.dumps(ind, ensure_ascii=False)}\n"
              f"필요한 연도: {min(years)}~{max(years)} (적어도 2010~2021은 있어야 검증 가능)\n"
              f"이미 있는 외부 데이터(중복 금지): {json.dumps([c['series'] for c in external.catalog()], ensure_ascii=False)}")
    messages = [{"role": "user", "content": prompt}]
    passed, trace, hinted = None, [], False
    for step in range(max_steps):
        if budget.exhausted(reserve=min(0.1, budget.limit * 0.2)):
            return {"status": "budget", "series": series, "trace": trace}
        resp = client.beta.messages.create(
            model=MODEL, max_tokens=16000, system=SYSTEM, tools=TOOLS, messages=messages,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "high"}, cache_control={"type": "ephemeral"},
        )
        budget.record(f"scout:{series}", resp)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "refusal":
            return {"status": "refusal", "series": series, "trace": trace}
        if resp.stop_reason == "pause_turn":  # 서버 쪽 검색이 길어져 잠시 멈춤 → 그대로 다시 보내면 이어서 진행
            continue
        for b in resp.content:
            if b.type == "server_tool_use":
                trace.append({"step": step, "tool": b.name, "input": getattr(b, "input", {})})
                log(f"[scout:{series}] {b.name}: {json.dumps(getattr(b, 'input', {}), ensure_ascii=False)[:150]}")
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            messages.append({"role": "user", "content": "도구를 써서 계속하라. 끝낼 때는 register_source 또는 give_up 을 호출하라."})
            continue
        results, done = [], None
        for b in calls:
            inp = b.input if isinstance(b.input, dict) else json.loads(b.input)
            if b.name == "try_source":
                chk = check(inp["spec"], years, loader)
                trace.append({"step": step, "tool": "try_source", "spec": inp["spec"], "ok": chk["ok"], "problems": chk.get("problems")})
                log(f"[scout:{series}] 명세 시험 {inp['spec'].get('url') or inp['spec'].get('wb_indicator')}: "
                    f"{'통과' if chk['ok'] else '실패 - ' + '; '.join(chk['problems'])}")
                if chk["ok"]:
                    passed = (inp["spec"], chk["_df"])
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": _brief(chk), "is_error": not chk["ok"]})
            elif b.name == "register_source":
                if passed is None:
                    results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                    "content": "검사를 통과한 명세가 없어 등록할 수 없다. try_source 부터 통과시켜라."})
                    continue
                entry = _register(series, passed[0], passed[1], inp, hyp.get("id", ""))
                log(f"[scout:{series}] 등록: {entry['desc']} ({entry['how']})")
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": "등록 완료"})
                done = {"status": "registered", "series": series, "source": entry, "trace": trace}
            elif b.name == "give_up":
                log(f"[scout:{series}] 포기: {inp['reason']}")
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": "기록함"})
                done = {"status": "gave_up", "series": series, "reason": inp["reason"], "tried": inp["tried"], "trace": trace}
            else:
                results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True, "content": f"알 수 없는 도구 {b.name}"})
        fails = sum(1 for t in trace if t["tool"] == "try_source" and not t["ok"])
        if not done and fails >= 4 and not hinted:  # 같은 곳만 계속 고치다 돈을 쓰지 않도록 전략 전환을 요구
            results.append({"type": "text", "text": STRATEGY})
            hinted = True
        messages.append({"role": "user", "content": results})
        if done:
            return done
    return {"status": "steps", "series": series, "trace": trace}
