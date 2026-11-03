"""World Bank WDI (https://api.worldbank.org/v2) — 공식 API, 키 불필요.

오프라인 대안: WDI 벌크 CSV(WDICSV.csv)를 data/raw/ 에 두면 load_wdi_bulk_csv 로 읽는다.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import cached_get_json

API = "https://api.worldbank.org/v2"


def fetch_countries() -> pd.DataFrame:
    """국가 메타데이터(집계지역 제외)."""
    js = cached_get_json(f"{API}/country", {"format": "json", "per_page": 400})
    rows = []
    for c in js[1]:
        if c["region"]["id"] == "NA":  # 지역/소득 집계
            continue
        rows.append({"iso3": c["id"], "name": c["name"], "region": c["region"]["value"],
                     "income": c["incomeLevel"]["value"]})
    return pd.DataFrame(rows)


def fetch_series(code: str, start: int = 1985, end: int = 2025) -> pd.DataFrame:
    js = cached_get_json(f"{API}/country/all/indicator/{code}",
                         {"format": "json", "per_page": 30000, "date": f"{start}:{end}"})
    rows = [{"iso3": r["countryiso3code"], "year": int(r["date"]), "value": r["value"]}
            for r in (js[1] or []) if r["value"] is not None and r["countryiso3code"]]
    df = pd.DataFrame(rows, columns=["iso3", "year", "value"])
    df["series"] = f"WB:{code}"
    return df


def load_wdi_bulk_csv(path: Path, codes: list[str]) -> pd.DataFrame:
    raw = pd.read_csv(path)
    raw = raw[raw["Indicator Code"].isin(codes)]
    years = [c for c in raw.columns if c.isdigit()]
    long = raw.melt(id_vars=["Country Code", "Indicator Code"], value_vars=years,
                    var_name="year", value_name="value").dropna()
    long = long.rename(columns={"Country Code": "iso3"})
    long["year"] = long["year"].astype(int)
    long["series"] = "WB:" + long.pop("Indicator Code")
    return long[["iso3", "year", "value", "series"]]
