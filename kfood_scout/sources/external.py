"""외부 원천 레지스트리: 국가×연도 값이면 무엇이든 지표 원천. SOURCES 에 이름 하나만 등록하면 된다."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from .base import cached_get_json

RAW = Path(__file__).resolve().parents[2] / "data" / "external" / "raw"

SOURCES: dict[str, dict] = {
    "gtrends_kpop": {"kind": "gtrends", "keywords": ["K-pop", "kpop"], "desc": "구글 트렌드 K-pop 검색 관심도(국가별, 연간)"},
    "gtrends_kdrama": {"kind": "gtrends", "keywords": ["Korean drama", "K-drama"], "desc": "구글 트렌드 한국 드라마 검색 관심도"},
    "gtrends_kfood": {"kind": "gtrends", "keywords": ["Korean food", "ramyeon"], "desc": "구글 트렌드 한국 음식 검색 관심도"},
    "gtrends_learnkorean": {"kind": "gtrends", "keywords": ["learn Korean", "Korean language"],
                            "desc": "구글 트렌드 한국어 학습 검색 관심도(한류 동호회 통계의 대체: 국가별 연간 자료가 PDF로만 있어 자동화 불가)"},
    "kto_visitors": {"kind": "kto", "file": "kto_visitors.csv",
                     "desc": "국적별 방한 외래관광객 수(한국관광공사 관광지식정보시스템 입국관광통계, 2005~)",
                     "how": "know.tour.go.kr/stat/entryTourStatDis19Re.do 국적별·연간 조회를 fetch_kto_visitors 가 자동 수집"},
    "kf_hallyu_members": {"kind": "file", "file": "kf_hallyu_members.csv",
                          "desc": "국가별 한류 동호회 회원 수(외교부·한국국제교류재단 「지구촌 한류현황」 책자, 비정기 PDF) — 선택",
                          "how": "책자 PDF의 국가별 표 → iso3,year,value CSV (자동화 대상 아님)"},
}


AUTO_SOURCES = Path(__file__).resolve().parents[2] / "config" / "sources" / "auto_sources.yaml"
_BUILTIN = set(SOURCES)


def load_auto_sources() -> None:
    """데이터 탐색 에이전트(agent/scout.py)가 찾아 등록한 원천을 SOURCES 에 합친다."""
    import yaml

    for k in [k for k in SOURCES if k not in _BUILTIN]:
        del SOURCES[k]
    if AUTO_SOURCES.exists():
        for name, spec in (yaml.safe_load(AUTO_SOURCES.read_text()) or {}).items():
            if name not in _BUILTIN:
                SOURCES[name] = spec


load_auto_sources()

def catalog() -> list[dict]:
    out = []
    for name, s in SOURCES.items():
        ready = s["kind"] in ("gtrends", "kto") or (RAW / s["file"]).exists()
        out.append({"series": name, "desc": s["desc"], "kind": s["kind"], "ready": ready, "how": s.get("how", ""),
                    **({"found_by_agent": True, "notes": s.get("notes", "")} if name not in _BUILTIN else {})})
    return out


def _iso2_to_iso3() -> dict[str, str]:
    js = cached_get_json("https://api.worldbank.org/v2/country", {"format": "json", "per_page": 400})
    return {c["iso2Code"]: c["id"] for c in js[1] if c.get("iso2Code")}


def _name_to_iso3() -> dict[str, str]:
    js = cached_get_json("https://api.worldbank.org/v2/country", {"format": "json", "per_page": 400})
    return {c["name"].lower(): c["id"] for c in js[1]}


def _gtrends(keywords: list[str], years: list[int], log=print) -> pd.DataFrame:
    from pytrends.request import TrendReq

    iso = _iso2_to_iso3()
    py = TrendReq(hl="en-US", tz=0)  # retries 옵션은 urllib3 2.x 에서 method_whitelist 오류 → 재시도는 아래 루프가 담당
    # 주의: 키워드를 여러 개 한 요청에 넣으면 interest_by_region 은 '나라마다 키워드끼리 나눈 비율(합 100)'을 준다.
    # 그걸 합치면 데이터가 있는 나라는 전부 100이 된다(2026-11-03 맥북 실행에서 확인). 그래서 키워드마다 따로 요청하고
    # (각각 가장 높은 나라 = 100 인 국가 간 척도), 키워드끼리는 평균한다.
    frames = []
    for kw in keywords:
        rows = []
        for y in years:
            if y < 2004:
                continue
            for attempt in range(5):
                try:
                    py.build_payload([kw], timeframe=f"{y}-01-01 {y}-12-31")
                    df = py.interest_by_region(resolution="COUNTRY", inc_low_vol=True, inc_geo_code=True)
                    break
                except Exception as e:  # noqa: BLE001
                    log(f"[gtrends] {kw} {y} 재시도 {attempt + 1}: {e}")
                    time.sleep(30 * (attempt + 1))
            else:
                raise RuntimeError(f"구글 트렌드 수집 실패: {kw} {y}")
            for code, v in zip(df["geoCode"], df[kw]):
                if code in iso:
                    rows.append((iso[code], y, float(v)))
            time.sleep(5)
        frames.append(pd.DataFrame(rows, columns=["iso3", "year", "value"]))
    out = pd.concat(frames).groupby(["iso3", "year"], as_index=False)["value"].mean()
    nz = out[out.value > 0].groupby("year")["value"].nunique()
    if len(nz) and nz.median() < 5:
        log(f"[gtrends] 경고: {keywords} 연도별 고유값 중앙값 {nz.median():.0f}개 — 값이 퇴화했을 수 있음")
    return out
    return pd.DataFrame(rows, columns=["iso3", "year", "value"])


def _file(spec: dict, years: list[int]) -> pd.DataFrame | None:
    p = RAW / spec["file"]
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if "iso3" not in df.columns:
        m = _name_to_iso3()
        df["iso3"] = df["country"].str.lower().map(m)
    df = df.dropna(subset=["iso3", "value"])
    return df[df.year.isin(years)][["iso3", "year", "value"]].astype({"year": int, "value": float})


KTO_PAGE = "https://know.tour.go.kr/stat/entryTourStatDis19Re.do"
KTO_DATA = "https://know.tour.go.kr/stat/entryTourStatDis_DataXML.do"
KTO_ISO3 = {
    "일본": "JPN", "중국": "CHN", "대만": "TWN", "필리핀": "PHL", "홍콩": "HKG", "태국": "THA", "말레이시아": "MYS",
    "싱가포르": "SGP", "인도네시아": "IDN", "인도": "IND", "베트남": "VNM", "미얀마": "MMR", "몽골": "MNG",
    "스리랑카": "LKA", "파키스탄": "PAK", "방글라데시": "BGD", "우즈베키스탄": "UZB", "터키": "TUR", "이스라엘": "ISR",
    "이란": "IRN", "카자흐스탄": "KAZ", "요르단": "JOR", "사우디아라비아": "SAU", "이라크": "IRQ", "미국": "USA",
    "캐나다": "CAN", "브라질": "BRA", "멕시코": "MEX", "칠레": "CHL", "아르헨티나": "ARG", "콜롬비아": "COL",
    "페루": "PER", "베네수엘라": "VEN", "에콰도르": "ECU", "쿠바": "CUB", "러시아(연방)": "RUS", "독일": "DEU",
    "영국": "GBR", "프랑스": "FRA", "네덜란드": "NLD", "우크라이나": "UKR", "이탈리아": "ITA", "불가리아": "BGR",
    "스웨덴": "SWE", "폴란드": "POL", "덴마크": "DNK", "그리스": "GRC", "스위스": "CHE", "노르웨이": "NOR",
    "스페인": "ESP", "루마니아": "ROU", "벨기에": "BEL", "오스트레일리아": "AUS", "뉴질랜드": "NZL", "키리바시": "KIR",
    "피지": "FJI", "남아프리카공화국": "ZAF", "나이지리아": "NGA", "이집트": "EGY",
}
KTO_SKIP_CODES = {"1", "997", "999"}  # 대륙 합계, '기타'·'미상', 교포


def fetch_kto_visitors(years: list[int], log=print) -> pd.DataFrame:
    """관광지식정보시스템 입국관광통계 '국적별 입국'(연간) 조회를 재현. 원본 XML 은 data/external/raw/kto_visitors_raw.xml."""
    import xml.etree.ElementTree as ET

    import requests

    s = requests.Session()
    s.get(KTO_PAGE, timeout=60)
    form = {"searchDivision": "entryNationality", "searchDateDivision": "YEAR", "searchStartYear": str(min(years)),
            "searchEndYear": str(max(years)), "searchStartMonth": "01", "searchEndMonth": "12", "mergyYN": "N", "advancedSearchYn": "N"}
    r = s.post(KTO_DATA, data=form, headers={"Referer": KTO_PAGE}, timeout=120)
    r.raise_for_status()
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "kto_visitors_raw.xml").write_bytes(r.content)
    rows, unmatched = [], []
    for row in ET.fromstring(r.content).findall("row"):
        name, code = (row.findtext("NAT_NM") or "").replace(" ", ""), (row.findtext("TS_ENT_NAT_CD") or "").strip()
        if code in KTO_SKIP_CODES:
            continue
        iso = KTO_ISO3.get(name)
        if not iso:
            unmatched.append(name)
            continue
        for y in years:
            v = row.findtext(f"CUR_{y}")
            if v not in (None, ""):
                rows.append((iso, y, float(v)))
    if unmatched:
        log(f"[kto] 매핑 못 한 국적명: {unmatched}")
    return pd.DataFrame(rows, columns=["iso3", "year", "value"])


def fetch(name: str, years: list[int], log=print) -> pd.DataFrame | None:
    if name not in SOURCES:
        raise KeyError(f"외부 원천 '{name}' 미등록 (sources/external.SOURCES 에 추가)")
    spec = SOURCES[name]
    if spec["kind"] == "gtrends":
        log(f"[external] 구글 트렌드 {name}: {len(years)}개 연도")
        return _gtrends(spec["keywords"], years, log)
    if spec["kind"] == "kto":
        log(f"[external] 한국관광공사 국적별 입국 {name}: {len(years)}개 연도")
        try:
            return fetch_kto_visitors(years, log)
        except NotImplementedError as e:
            log(f"[external] {name}: {e}")
            return None
    if spec["kind"] == "file":
        df = _file(spec, years)
        if df is None:
            log(f"[external] {name}: 파일 없음 → {RAW / spec['file']} ({spec.get('how', '')})")
        return df
    raise ValueError(spec["kind"])
