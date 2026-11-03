"""다른 방법 3가지가 함께 쓰는 것: 저장 데이터 읽기, 후보 거르기, 백분위.

기존 모듈(three.py 등)은 import 하지 않는다. data/store 와 config 는 읽기만 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..config import CONFIG, ROOT

STORE = ROOT / "data" / "store"
OUT = ROOT / "outputs" / "alt_methods"


def load_cfg(category: str | None = None) -> dict:
    cfg = yaml.safe_load((CONFIG / "alt" / "methods.yaml").read_text())
    cfg["category"] = category or cfg["category"]
    cats = yaml.safe_load((CONFIG / "categories.yaml").read_text())
    cfg["hs"] = list(cats[cfg["category"]]["hs_codes"].keys())
    cfg["category_name_ko"] = cats[cfg["category"]]["name_ko"]
    return cfg


def _csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["iso3", "year", "value"])
    d = pd.read_csv(path)
    return d.astype({"iso3": str, "year": int, "value": float})


def wide(df: pd.DataFrame) -> pd.DataFrame:
    """iso3 × year 표."""
    if df.empty:
        return pd.DataFrame()
    return df.groupby(["iso3", "year"]).value.sum().unstack()


def trade(flow: str, hs: list[str]) -> pd.DataFrame:
    """flow: KOR_X(한국→상대국 수출), M(각국 대세계 수입). HS 코드 합계, USD."""
    return wide(pd.concat([_csv(STORE / f"comtrade_{flow}" / f"{h}.csv") for h in hs], ignore_index=True))


def wb(code: str) -> pd.DataFrame:
    return wide(_csv(STORE / "worldbank" / f"{code}.csv"))


def ext(name: str) -> pd.DataFrame:
    return wide(_csv(STORE / "external" / f"{name}.csv"))


def avg_last(w: pd.DataFrame, year: int, n: int) -> pd.Series:
    cols = [y for y in range(year - n + 1, year + 1) if y in w.columns]
    return w[cols].mean(axis=1) if cols else pd.Series(dtype=float)


def pct(s: pd.Series) -> pd.Series:
    """나라들 사이 백분위(0~100). 값이 없으면 NaN."""
    s = s.dropna()
    if len(s) < 2:
        return s * np.nan
    return (s.rank(method="average") - 1) / (len(s) - 1) * 100


def names() -> dict:
    """iso3 → 한글 이름(있으면). 없으면 iso3."""
    p = CONFIG / "screen" / "screen.yaml"
    ko = {}
    try:
        ko = (yaml.safe_load(p.read_text()) or {}).get("names_ko", {}) or {}
    except Exception:
        pass
    base = {"PHL": "필리핀", "MYS": "말레이시아", "SGP": "싱가포르", "THA": "태국", "IDN": "인도네시아",
            "NLD": "네덜란드", "ARE": "아랍에미리트", "GBR": "영국", "DEU": "독일", "NZL": "뉴질랜드",
            "MNG": "몽골", "SAU": "사우디아라비아", "HKG": "홍콩", "FRA": "프랑스", "MEX": "멕시코",
            "BRA": "브라질", "KHM": "캄보디아", "UZB": "우즈베키스탄", "KWT": "쿠웨이트", "QAT": "카타르",
            "ISR": "이스라엘", "TUR": "튀르키예", "CHL": "칠레", "PER": "페루", "ITA": "이탈리아",
            "ESP": "스페인", "SWE": "스웨덴", "POL": "폴란드", "IND": "인도", "VNM": "베트남",
            "USA": "미국", "CHN": "중국", "JPN": "일본", "CAN": "캐나다", "AUS": "호주", "KAZ": "카자흐스탄",
            "BRN": "브루나이", "LAO": "라오스", "NPL": "네팔", "BGD": "방글라데시", "LKA": "스리랑카",
            "OMN": "오만", "BHR": "바레인", "EGY": "이집트", "ZAF": "남아프리카공화국", "NGA": "나이지리아",
            "GTM": "과테말라", "PAN": "파나마", "CRI": "코스타리카", "COL": "콜롬비아", "ARG": "아르헨티나",
            "CHE": "스위스", "NOR": "노르웨이", "DNK": "덴마크", "BEL": "벨기에", "AUT": "오스트리아",
            "IRL": "아일랜드", "PRT": "포르투갈", "GRC": "그리스", "CZE": "체코", "HUN": "헝가리",
            "ROU": "루마니아", "UKR": "우크라이나", "RUS": "러시아", "PAK": "파키스탄", "MMR": "미얀마",
            "JOR": "요르단", "LBN": "레바논", "MAC": "마카오", "FJI": "피지", "PNG": "파푸아뉴기니",
            "MDV": "몰디브", "KGZ": "키르기스스탄", "TJK": "타지키스탄", "AZE": "아제르바이잔", "GEO": "조지아"}
    base.update(ko)
    return base


def candidates(cfg: dict) -> tuple[list[str], dict, list[str]]:
    """후보 나라 목록과, 빠진 나라별 이유. 기존 3대 기준 모델과 같은 규칙(롯데 기진출국·사전 필터·한국 수출 상위 5개국)."""
    y, n = cfg["now_year"], cfg["smooth_years"]
    pop = wb("SP.POP.TOTL")
    m = trade("M", cfg["hs"])
    kor = trade("KOR_X", cfg["hs"])
    p = avg_last(pop, y, 3)
    universe = sorted((set(p[p >= cfg["exclude"]["min_population"]].index) & set(m.index)) - {"KOR"})  # 한국 자신은 제외
    why: dict[str, list[str]] = {c: [] for c in universe}

    ex = cfg["exclude"]
    if ex.get("lotte_entries"):
        ent = yaml.safe_load((CONFIG / "entries" / "lotte_wellfood.yaml").read_text())
        for e in ent["entries"]:
            if e["iso3"] in why:
                why[e["iso3"]].append("롯데 기진출국")
    if ex.get("hard_filter"):
        filt = yaml.safe_load((CONFIG / "filters" / "hard_filter.yaml").read_text())
        for r in filt["rules"]:
            if r["kind"] == "list" and r.get("action") == "exclude":
                for c in r["iso3"]:
                    if c in why:
                        why[c].append(r["name_ko"])
            elif r["kind"] == "wgi" and "exclude_below" in r:
                v = avg_last(wb(r["series"]), y, r.get("years", 3))
                for c in why:
                    if c in v and v[c] < r["exclude_below"]:
                        why[c].append(f"{r['name_ko']}({v[c]:.2f})")
    k = avg_last(kor, y, n).reindex(universe).fillna(0)
    for c in k.nlargest(ex["big_n"]).index:
        why[c].append("한국 수출 상위 5개국(지킬 시장)")
    cand = [c for c in universe if not why[c]]
    return cand, {c: w for c, w in why.items() if w}, universe


def save(name: str, obj) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    if isinstance(obj, str):
        p.write_text(obj)
    else:
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=float))
    return p
