"""깔때기에 필요한 나라별 지표 표(iso3 × 지표)를 원천 저장소(data/store)에서 만든다.

- 무역(UN Comtrade)·세계은행·구글 트렌드·방한객: 맥북에서 받아 둔 data/store 를 읽기만 한다(새 호출 0).
- 새로 필요한 공개 데이터(물가·환율·물류지수·GDP 성장률, 국가 좌표·언어)는 GitHub 미러에서 한 번 받아
  data/store/wdi_mirror/, data/store/ref/ 에 저장한다(무료, 키 불필요). 이후엔 저장분만 쓴다.
"""
from __future__ import annotations

import io
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..config import ROOT

STORE = ROOT / "data" / "store"
WDI_URL = "https://raw.githubusercontent.com/datasets/world-development-indicators/master/indicators/{code}/data.csv"
REF_URL = "https://raw.githubusercontent.com/mledoze/countries/master/countries.json"
SEOUL = (37.57, 126.98)
WDI_CODES = {"inflation": "fp.cpi.totl.zg", "fx": "pa.nus.fcrf", "lpi": "lp.lpi.ovrl.xq", "gdp_growth": "ny.gdp.mktp.kd.zg"}


def _get(url: str) -> str:
    import requests

    r = requests.get(url, timeout=90)
    r.raise_for_status()
    return r.text


def wdi_mirror(code: str, fetch: bool = True, log=print) -> pd.DataFrame:
    p = STORE / "wdi_mirror" / f"{code}.csv"
    if not p.exists():
        if not fetch:
            return pd.DataFrame(columns=["iso3", "year", "value"])
        log(f"[funnel] 세계은행 WDI 미러 {code} 받기")
        d = pd.read_csv(io.StringIO(_get(WDI_URL.format(code=code))))
        d = d.rename(columns={"Country Code": "iso3", "Year": "year", "Value": "value"})[["iso3", "year", "value"]].dropna()
        p.parent.mkdir(parents=True, exist_ok=True)
        d.to_csv(p, index=False)
    return pd.read_csv(p).astype({"iso3": str, "year": int, "value": float})


def country_ref(fetch: bool = True, log=print) -> pd.DataFrame:
    """국가 중심 좌표·공용어(영어 여부). mledoze/countries(공개 데이터셋)."""
    p = STORE / "ref" / "countries_ref.csv"
    if not p.exists():
        if not fetch:
            return pd.DataFrame(columns=["iso3", "lat", "lon", "english"])
        log("[funnel] 국가 좌표·언어(mledoze/countries) 받기")
        rows = [{"iso3": c["cca3"], "lat": c["latlng"][0] if c.get("latlng") else np.nan,
                 "lon": c["latlng"][1] if c.get("latlng") else np.nan,
                 "english": "eng" in (c.get("languages") or {})} for c in json.loads(_get(REF_URL))]
        p.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(p, index=False)
    return pd.read_csv(p)


def _csv(kind: str, key: str) -> pd.DataFrame:
    p = STORE / kind / f"{key}.csv"
    if not p.exists():
        return pd.DataFrame(columns=["iso3", "year", "value"])
    return pd.read_csv(p).astype({"iso3": str, "year": int, "value": float})


def _wide(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    return df.pivot_table(index="iso3", columns="year", values="value", aggfunc="sum")


def _flow(flow: str, hs: list[str]) -> pd.DataFrame:
    parts = [_csv(f"comtrade_{flow}", h) for h in hs]
    d = pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else _csv("x", "x")
    return _wide(d.groupby(["iso3", "year"], as_index=False)["value"].sum()) if len(d) else pd.DataFrame()


def _avg(w: pd.DataFrame, y0: int, y1: int) -> pd.Series:
    cols = [c for c in range(y0, y1 + 1) if c in w.columns]
    return w[cols].mean(axis=1) if cols else pd.Series(dtype=float)


def _latest(w: pd.DataFrame, year: int, back: int = 3) -> pd.Series:
    out = pd.Series(np.nan, index=w.index)
    for y in range(year, year - back - 1, -1):
        if y in w.columns:
            out = out.fillna(w[y])
    return out


def _cagr(a: pd.Series, b: pd.Series, n: int) -> pd.Series:
    ok = (a > 0) & (b > 0)
    return ((b[ok] / a[ok]) ** (1 / n) - 1) * 100


def _haversine(lat, lon):
    la1, lo1 = map(math.radians, SEOUL)
    la2, lo2 = np.radians(lat), np.radians(lon)
    h = np.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(h))


def fta_years(year: int, cap: int = 10) -> pd.Series:
    cfg = yaml.safe_load((ROOT / "config" / "funnel" / "korea_fta.yaml").read_text(encoding="utf-8"))
    start: dict[str, int] = {}
    for g in cfg["groups"].values():
        for c in g["iso3"]:
            start[c] = min(start.get(c, 9999), g["year"])
    return pd.Series({c: float(min(cap, max(0, year - s + 1))) for c, s in start.items()})


def build(hs: list[str], year: int = 2024, fetch: bool = True, log=print) -> tuple[pd.DataFrame, pd.DataFrame]:
    """→ (지표 표: iso3 index, 국가 정보: iso3/name/region/income/english/halal)."""
    y3 = (year - 2, year)            # 3년 평균
    y3p = (year - 7, year - 5)       # 5년 전 3년 평균(성장률 시작점)
    M, X, K, J = (_flow(f, hs) for f in ("M", "X", "KOR_X", "JPN_X"))
    wb = {c: _wide(_csv("worldbank", c)) for c in
          ["SP.POP.TOTL", "NE.CON.PRVT.PC.KD", "NY.GDP.PCAP.PP.KD", "SP.POP.0014.TO.ZS", "SP.URB.TOTL.IN.ZS",
           "PV.EST", "RL.EST", "CC.EST"]}
    ex = {c: _wide(_csv("external", c)) for c in ["gtrends_kfood", "gtrends_kpop", "gtrends_learnkorean", "kto_visitors"]}
    wd = {k: _wide(wdi_mirror(c, fetch, log)) for k, c in WDI_CODES.items()}

    pop_w = wb["SP.POP.TOTL"]
    pop = _latest(pop_w, year)
    imp = _avg(M, *y3)
    kor = _avg(K, *y3).reindex(imp.index).fillna(0.0)
    jpn = _avg(J, *y3).reindex(imp.index).fillna(0.0) if not J.empty else pd.Series(0.0, index=imp.index)
    hh_pc = _latest(wb["NE.CON.PRVT.PC.KD"], year)
    urb = wb["SP.URB.TOTL.IN.ZS"]
    fx = wd["fx"]
    fx_chg = fx.pct_change(axis=1, fill_method=None) * 100
    fx_cols = [c for c in fx_chg.columns if year - 9 <= c <= year]
    fx_drop = fx_chg[[c for c in fx_chg.columns if year - 14 <= c <= year]].max(axis=1).clip(lower=0)  # 최대 연간 절하율(%)
    mcols = [c for c in M.columns if c <= year]
    m3 = (M[mcols].shift(-3, axis=1) / M[mcols] - 1).min(axis=1).clip(upper=0) * 100 if len(mcols) > 3 else pd.Series(dtype=float)

    ref = country_ref(fetch, log).set_index("iso3")
    dist = pd.Series(_haversine(ref.lat.values, ref.lon.values), index=ref.index)

    T = pd.DataFrame({
        "population": pop,
        "population_cagr": _cagr(_latest(pop_w, year - 5), pop, 5),
        "import_usd": imp,
        "import_market_size": np.log(imp.where(imp > 0)),
        "import_cagr": _cagr(_avg(M, *y3p), imp, 5),
        "hh_consumption_total": np.log(hh_pc * pop),
        "hh_consumption_pc_cagr": _cagr(_avg(wb["NE.CON.PRVT.PC.KD"], *y3p), _avg(wb["NE.CON.PRVT.PC.KD"], *y3), 5),
        "gdp_growth": _avg(wd["gdp_growth"], year - 4, year),
        "gdp_pc_ppp": _latest(wb["NY.GDP.PCAP.PP.KD"], year),
        "youth_share": _latest(wb["SP.POP.0014.TO.ZS"], year),
        "urbanization_change": _latest(urb, year) - _latest(urb, year - 5),
        "import_pc": imp / pop,
        "kfood_interest": _avg(ex["gtrends_kfood"], *y3),
        "kpop_interest": _avg(ex["gtrends_kpop"], *y3),
        "learn_korean_interest": _avg(ex["gtrends_learnkorean"], *y3),
        "korea_visitors_pc": _avg(ex["kto_visitors"], *y3) / pop * 1000,   # 인구 천 명당
        "korea_exports_usd": kor,
        "korea_exports_size": np.log1p(kor),
        "korea_share": kor / imp * 100,
        "korea_share_change": kor / imp * 100 - (_avg(K, *y3p) / _avg(M, *y3p) * 100).reindex(imp.index).fillna(0),
        "korea_exports_change": _avg(K, year - 1, year).reindex(imp.index).fillna(0) - _avg(K, year - 4, year - 3).reindex(imp.index).fillna(0),
        "distance_km": dist,
        "fta_years": fta_years(year),
        "japan_share": jpn / imp * 100,
        "political_stability": _avg(wb["PV.EST"], *y3),
        "governance": (_avg(wb["RL.EST"], *y3) + _avg(wb["CC.EST"], *y3)) / 2,
        "inflation": _avg(wd["inflation"], year - 4, year),
        "fx_volatility": fx_chg[fx_cols].std(axis=1) if fx_cols else np.nan,
        "logistics": _latest(wd["lpi"], year, back=6),
        "worst_import_drop_3y": m3,
        "worst_fx_drop_1y": fx_drop,
    })
    T.index.name = "iso3"
    T["fta_years"] = T["fta_years"].fillna(0.0)
    T["korea_visitors_pc"] = T["korea_visitors_pc"]  # 방한객 통계에 없는 나라는 결측(중립 50점)
    cty = pd.read_csv(STORE / "countries.csv")
    cty["region"] = cty.region.str.strip()
    cty = cty.set_index("iso3")
    cty["english"] = ref.english.reindex(cty.index).fillna(False).astype(bool)
    return T, cty
