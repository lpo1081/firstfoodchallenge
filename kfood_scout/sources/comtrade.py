"""UN Comtrade v1 API (https://comtradeapi.un.org).

- 키가 없으면 public preview 엔드포인트(호출당 최대 500건)를 쓴다.
- 환경변수 COMTRADE_API_KEY 가 있으면 정식 엔드포인트(무료 키: 일 500회, 호출당 10만건)를 쓴다.
- 보고국이 해당 연도 무역을 신고하지 않은 경우, 상대국들이 신고한 수출(미러 데이터)로 보완한다.

오프라인 대안: Comtrade 웹에서 내려받은 CSV를 data/raw/comtrade_*.csv 로 두면 load_comtrade_csv 로 읽는다.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from .base import cached_get_json

PREVIEW = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
FULL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
REPORTERS = "https://comtradeapi.un.org/files/v1/app/reference/Reporters.json"


def _endpoint():
    key = os.environ.get("COMTRADE_API_KEY")
    if key:
        return FULL, {"Ocp-Apim-Subscription-Key": key}
    return PREVIEW, None


def reporter_codes() -> pd.DataFrame:
    js = cached_get_json(REPORTERS)
    rows = [{"m49": r["id"], "iso3": r.get("reporterCodeIsoAlpha3")} for r in js["results"]
            if r.get("reporterCodeIsoAlpha3") and not r.get("isGroup")]
    return pd.DataFrame(rows).drop_duplicates("iso3")


def _periods(years) -> list[str]:
    """키가 있으면 12개 연도를 묶어 1회 호출(정식 API는 호출당 10만 건), 없으면 연도별(preview 500건 제한)."""
    if os.environ.get("COMTRADE_API_KEY"):
        ys = sorted(years)
        return [",".join(map(str, ys[i:i + 12])) for i in range(0, len(ys), 12)]
    return [str(y) for y in years]


def _get(params: dict) -> list[dict]:
    url, headers = _endpoint()
    base = {"customsCode": "C00", "motCode": "0", "partner2Code": "0", "includeDesc": "true"}
    js = cached_get_json(url, {**base, **params}, headers=headers, sleep=1.1)
    return js.get("data") or []


def fetch_world_flows(hs_codes: list[str], flow: str, years: list[int]) -> pd.DataFrame:
    """모든 보고국의 대(對)세계 수입/수출액. flow: 'M' or 'X'. 반환: iso3, year, hs, value(USD)."""
    rows = []
    for period in _periods(years):
        for hs in hs_codes:  # preview 500건 제한 때문에 코드별로 나눠 호출
            for r in _get({"period": period, "cmdCode": hs, "flowCode": flow, "partnerCode": "0"}):
                rows.append({"iso3": r.get("reporterISO"), "year": int(r["refYear"]), "hs": r["cmdCode"],
                             "value": r.get("primaryValue") or r.get("cifvalue") or r.get("fobvalue")})
    return pd.DataFrame(rows, columns=["iso3", "year", "hs", "value"]).dropna()


def fetch_mirror_imports(target_m49: int, hs_codes: list[str], years: list[int]) -> pd.DataFrame:
    """target 국가로 향한 상대국 수출 합계 = target 의 미러 수입."""
    rows = []
    for period in _periods(years):
        for hs in hs_codes:  # preview 500건 제한 때문에 코드별 호출
            for r in _get({"period": period, "cmdCode": hs, "flowCode": "X", "partnerCode": str(target_m49)}):
                rows.append({"year": int(r["refYear"]), "hs": r["cmdCode"], "value": r.get("primaryValue")})
    return pd.DataFrame(rows, columns=["year", "hs", "value"]).dropna()


def load_comtrade_csv(paths: list[Path]) -> pd.DataFrame:
    """Comtrade 웹 다운로드 CSV(refYear, reporterISO, flowCode, cmdCode, primaryValue)."""
    frames = []
    for p in paths:
        d = pd.read_csv(p, dtype={"cmdCode": str}, encoding_errors="ignore")
        d = d[d["partnerCode"].astype(str).isin(["0"])] if "partnerCode" in d else d
        frames.append(d.rename(columns={"reporterISO": "iso3", "refYear": "year", "cmdCode": "hs",
                                        "primaryValue": "value", "flowCode": "flow"})
                      [["iso3", "year", "hs", "value", "flow"]])
    return pd.concat(frames, ignore_index=True)


AGG_PREFIX = ("X", "_")


def fetch_korea_exports(hs_codes: list[str], years: list[int]) -> pd.DataFrame:
    """한국(410)의 상대국별 수출. 반환: iso3(상대국), year, hs, value. World·지역집계 제외."""
    rows = []
    for period in _periods(years):
        for hs in hs_codes:
            for r in _get({"period": period, "cmdCode": hs, "flowCode": "X", "reporterCode": "410"}):
                iso = r.get("partnerISO")
                if str(r.get("partnerCode")) == "0" or not iso or iso.startswith(AGG_PREFIX) or iso == "W00":
                    continue
                rows.append({"iso3": iso, "year": int(r["refYear"]), "hs": r["cmdCode"], "value": r.get("primaryValue")})
    return pd.DataFrame(rows, columns=["iso3", "year", "hs", "value"]).dropna()
