"""원천 데이터 저장소: HS 코드 1개 × 흐름 1개 = 파일 1개, WB 지표 1개 = 파일 1개.

카테고리는 HS 코드의 '묶음'일 뿐이므로, 카테고리를 추가·삭제해도 이미 받은 코드는 다시 받지 않는다.
패널(iso3, year, series, value)은 필요할 때 저장소에서 조립한다.

새 흐름(예: 일본의 상대국별 수출 JPN_X)을 쓰려면 FETCHERS 에 함수 하나만 등록하면 된다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import ROOT, Criterion
from .sources import comtrade, external, worldbank

STORE = ROOT / "data" / "store"


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={"partnerISO": "iso3", "reporterISO": "iso3", "refYear": "year", "primaryValue": "value"})
    return df[["iso3", "year", "value"]].dropna()


# 흐름 이름 → (hs, years) 를 받아 iso3/year/value 를 돌려주는 함수
FETCHERS = {
    "M": lambda hs, ys: _norm(comtrade.fetch_world_flows([hs], "M", ys)),
    "X": lambda hs, ys: _norm(comtrade.fetch_world_flows([hs], "X", ys)),
    "KOR_X": lambda hs, ys: _norm(comtrade.fetch_korea_exports([hs], ys)),
}


def _paths(kind: str, key: str) -> tuple[Path, Path]:
    d = STORE / kind
    d.mkdir(parents=True, exist_ok=True)
    safe = key.replace("/", "_")
    return d / f"{safe}.csv", d / f"{safe}.years.json"


def _load(kind, key):
    p, meta = _paths(kind, key)
    df = pd.read_csv(p) if p.exists() else pd.DataFrame(columns=["iso3", "year", "value"])
    done = set(json.loads(meta.read_text())) if meta.exists() else set()
    df = df.astype({"iso3": str, "year": int, "value": float}) if len(df) else df
    return df, done


def _save(kind, key, df, done):
    p, meta = _paths(kind, key)
    df.drop_duplicates(["iso3", "year"], keep="last").sort_values(["iso3", "year"]).to_csv(p, index=False)
    meta.write_text(json.dumps(sorted(done)))


def comtrade_hs(flow: str, hs: str, years: list[int], fetch: bool = True, log=print) -> pd.DataFrame:
    """HS 코드 1개의 흐름 데이터. 아직 안 받은 연도만 받는다(데이터가 없던 연도도 '받음'으로 기록)."""
    kind = f"comtrade_{flow}"
    df, done = _load(kind, hs)
    missing = [y for y in years if y not in done]
    if missing and fetch:
        log(f"[store] {flow} {hs}: {len(missing)}개 연도 수집")
        new = FETCHERS[flow](hs, missing)
        df = pd.concat([df, new], ignore_index=True)
        done |= set(missing)
        _save(kind, hs, df, done)
    return df[df.year.isin(years)]


def wb_series(code: str, years: list[int], fetch: bool = True, log=print) -> pd.DataFrame:
    df, done = _load("worldbank", code)
    if not set(years) <= done and fetch:
        log(f"[store] WB {code}")
        new = worldbank.fetch_series(code, min(years), max(years))[["iso3", "year", "value"]]
        if new.empty:  # 못 받았으면 '받음'으로 기록하지 않음(다음 실행 때 다시 시도)
            log(f"[store] WB {code}: 값 없음")
            return df[df.year.isin(years)]
        df = pd.concat([df, new], ignore_index=True)
        done |= set(years)
        _save("worldbank", code, df, done)
    return df[df.year.isin(years)]


def external_series(name: str, years: list[int], fetch: bool = True, log=print) -> pd.DataFrame:
    """외부 원천(구글 트렌드, 방한 관광객 등) 1개 = 파일 1개. 원천 추가는 sources/external.SOURCES 에 등록만."""
    if external.SOURCES.get(name, {}).get("kind") == "file":  # 로컬 파일은 매번 다시 읽음(갱신 반영)
        df = external.fetch(name, years, log=log)
        return df if df is not None else pd.DataFrame(columns=["iso3", "year", "value"])
    df, done = _load("external", name)
    missing = [y for y in years if y not in done]
    if missing and fetch:
        new = external.fetch(name, missing, log=log)
        if new is not None:
            df = pd.concat([df, new[["iso3", "year", "value"]]], ignore_index=True)
            done |= set(missing)
            _save("external", name, df, done)
    return df[df.year.isin(years)]


def needs(category: str, categories: dict, criterion: Criterion) -> dict:
    """이 카테고리×기준 조합에 필요한 원천 목록."""
    hs = [str(h) for h in categories[category]["hs_codes"]]
    tg = criterion.target
    ext_target = tg.get("source") == "external"
    flows = sorted({i.flow for i in criterion.all_indicators() if i.source == "comtrade"}
                   | ({tg["series"]} if tg.get("series") and not ext_target else set())
                   | ({"M", "X"} if any(i.transform == "net_import_share" for i in criterion.all_indicators()) else set()))
    wb = sorted({i.series for i in criterion.all_indicators() if i.source == "worldbank"} | {"SP.POP.TOTL"})
    ex = sorted({i.series for i in criterion.all_indicators() if i.source == "external"}
                | ({tg["series"]} if ext_target else set()))
    return {"hs": hs, "flows": flows, "wb": wb, "ex": ex}


def pending_calls(category, categories, criterion, years) -> int:
    """아직 받지 않은 Comtrade 호출 수(쿼터 계획용)."""
    n = needs(category, categories, criterion)
    tot = 0
    for f in n["flows"]:
        for h in n["hs"]:
            _, done = _load(f"comtrade_{f}", h)
            tot += len([y for y in years if y not in done])
    return tot


def assemble_panel(category: str, categories: dict, criterion: Criterion, years: list[int],
                   fetch: bool = True, log=print) -> pd.DataFrame:
    n = needs(category, categories, criterion)
    frames = []
    for code in n["wb"]:
        d = wb_series(code, years, fetch, log).copy()
        d["series"] = f"WB:{code}"
        frames.append(d)
    for code in n.get("ex", []):
        d = external_series(code, years, fetch, log).copy()
        d["series"] = f"EX:{code}"
        frames.append(d)
    for f in n["flows"]:
        parts = [comtrade_hs(f, h, years, fetch, log) for h in n["hs"]]
        d = pd.concat(parts).groupby(["iso3", "year"], as_index=False)["value"].sum()
        d["series"] = f"CT:{category}:{f}"
        frames.append(d)
    out = pd.concat(frames, ignore_index=True)[["iso3", "year", "series", "value"]]
    return out.astype({"iso3": str, "year": int, "value": float})


def countries(fetch: bool = True) -> pd.DataFrame:
    p = STORE / "countries.csv"
    if not p.exists() and fetch:
        STORE.mkdir(parents=True, exist_ok=True)
        worldbank.fetch_countries().to_csv(p, index=False)
    if not p.exists() and (ROOT / "data" / "countries.csv").exists():
        return pd.read_csv(ROOT / "data" / "countries.csv")
    return pd.read_csv(p)
