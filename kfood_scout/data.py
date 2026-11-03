"""원천별 수집 결과를 하나의 long 패널(iso3, year, series, value)로 합친다.

panel.csv 하나만 있으면 이후 모든 계산(스코어, 검증, 대시보드)은 오프라인으로 반복 실행된다.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import ROOT, Criterion
from .sources import comtrade, worldbank

DATA = ROOT / "data"


def panel_path(category: str) -> Path:
    return DATA / f"panel_{category}.csv"


def build_panel(category: str, categories: dict, criterion: Criterion,
                start: int = 1985, end: int = 2024, mirror_iso3: dict[str, int] | None = None,
                log=print) -> pd.DataFrame:
    hs = list(categories[category]["hs_codes"].keys())
    frames = []
    DATA.mkdir(exist_ok=True)
    worldbank.fetch_countries().to_csv(DATA / "countries.csv", index=False)

    wb_codes = sorted({i.series for i in criterion.all_indicators() if i.source == "worldbank"}
                      | {"SP.POP.TOTL"})
    for code in wb_codes:
        log(f"[WB] {code}")
        frames.append(worldbank.fetch_series(code, start, end))

    flows = sorted({i.flow for i in criterion.all_indicators() if i.source == "comtrade"})
    years = list(range(max(start, 1988), end + 1))
    hs_detail = []
    for flow in flows:
        log(f"[Comtrade] flow={flow} HS={hs} {years[0]}-{years[-1]}")
        df = comtrade.fetch_world_flows(hs, flow, years)
        df["flow"] = flow
        hs_detail.append(df)
        agg = df.groupby(["iso3", "year"], as_index=False)["value"].sum()
        agg["series"] = f"CT:{category}:{flow}"
        frames.append(agg)

    panel = pd.concat(frames, ignore_index=True)

    # 미보고 국가-연도 보완(미러 데이터): 지정 국가만 (호출량 절약)
    if mirror_iso3 and "M" in flows:
        codes = comtrade.reporter_codes().set_index("iso3")["m49"]
        key = f"CT:{category}:M"
        have = panel[panel.series == key]
        for iso in mirror_iso3:
            got = set(have[have.iso3 == iso].year)
            # 역산에 쓰이는 구간(진출연도-7 ~ 진출연도-1)만 보완해 호출량을 줄인다
            entry_year = mirror_iso3[iso]
            missing = [y for y in years if y not in got and entry_year - 7 <= y <= entry_year - 1]
            if not missing or iso not in codes:
                continue
            log(f"[Comtrade mirror] {iso} {len(missing)}개 연도 보완")
            m = comtrade.fetch_mirror_imports(int(codes[iso]), hs, missing)
            if len(m):
                m = m.groupby("year", as_index=False)["value"].sum()
                m["iso3"], m["series"] = iso, key
                panel = pd.concat([panel, m], ignore_index=True)

    DATA.mkdir(exist_ok=True)
    panel.to_csv(panel_path(category), index=False)
    if hs_detail:
        pd.concat(hs_detail).to_csv(DATA / f"comtrade_hs_detail_{category}.csv", index=False)
    return panel


def load_panel(category: str) -> pd.DataFrame:
    return pd.read_csv(panel_path(category))


def load_countries() -> pd.DataFrame:
    return pd.read_csv(DATA / "countries.csv")
