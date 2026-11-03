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
    # 세계은행 WDI 의 GitHub 미러(raw.githubusercontent.com, 클라우드에서도 접속됨). 지표 코드 소문자.
    "wdi_fx": {"kind": "wdi_mirror", "code": "pa.nus.fcrf", "desc": "공식 환율(현지통화/USD, 연평균), WDI PA.NUS.FCRF"},
    "wdi_inflation": {"kind": "wdi_mirror", "code": "fp.cpi.totl.zg", "desc": "소비자물가 상승률(%), WDI FP.CPI.TOTL.ZG"},
    # 한국 FTA 발효 연도(config/sources/korea_fta.yaml) → 발효 후 경과 연수(0~10)
    "korea_fta_years": {"kind": "korea_fta", "desc": "한국과의 FTA 발효 후 경과 연수(0~10년), 산업통상자원부·Wikipedia 발효일"},
    "kf_hallyu_members": {"kind": "file", "file": "kf_hallyu_members.csv",
                          "desc": "국가별 한류 동호회 회원 수(외교부·한국국제교류재단 「지구촌 한류현황」 책자, 비정기 PDF) — 선택",
                          "how": "책자 PDF의 국가별 표 → iso3,year,value CSV (자동화 대상 아님)"},
    # UNIDO IDSB(ISIC Rev.4 4자리): 나라별 현지 생산·수입·수출·실소비(=생산+수입−수출), 2005~, 무료 API.
    # 1071 베이커리(비스킷 포함) + 1073 코코아·초콜릿·설탕 과자. 현지생산형 시장(인도 등)도 잡는 '현지 시장 크기'.
    "unido_snack_consumption": {"kind": "unido", "dataset": "IDSB", "revision": 4, "variable": "107",
                                "activities": ["1071", "1073"],
                                "desc": "UNIDO IDSB 과자류(1071+1073) 실소비(생산+수입−수출, USD)"},
    "unido_snack_output": {"kind": "unido", "dataset": "IDSB", "revision": 4, "variable": "100",
                           "activities": ["1071", "1073"],
                           "desc": "UNIDO IDSB 과자류(1071+1073) 현지 생산액(USD)"},
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
        ready = s["kind"] in ("gtrends", "kto", "unido", "wdi_mirror", "korea_fta") or (RAW / s.get("file", "")).is_file()
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


UNIDO = "https://stat.unido.org/portal/dataset"


def fetch_unido(spec: dict, years: list[int], log=print) -> pd.DataFrame:
    """UNIDO 통계 포털 API(무료, 키 없음). 나라마다 POST 1회(getData: datasetId·countryCode·variableCode·activityCodes·periods).
    응답 data[] = {p: 연도, a: 활동코드, v: 값, c: 국가코드}. 활동코드들을 합산해 iso3·year·value 로 돌려준다."""
    import requests

    meta = requests.get(f"{UNIDO}/getDataset/{spec['dataset']}/{spec['revision']}", timeout=60).json()
    rows = []
    for k, ctry in enumerate(meta["countries"]):
        body = {"datasetId": meta["id"], "countryCode": ctry["c"], "variableCode": spec["variable"],
                "activityCodes": spec["activities"], "periods": [str(y) for y in years], "fullPrecision": True}
        for attempt in range(3):
            try:
                r = requests.post(f"{UNIDO}/getData", json=body, timeout=60)
                if r.status_code == 200:
                    for d in r.json().get("data") or []:
                        if d.get("v") is not None and d.get("a") in spec["activities"]:
                            rows.append((ctry["iso3"], int(d["p"]), float(d["v"])))
                    break
                log(f"[unido] {ctry['iso3']} HTTP {r.status_code}: {r.text[:120]}")
                break
            except requests.RequestException as e:
                log(f"[unido] {ctry['iso3']} 재시도 {attempt + 1}: {e}")
                time.sleep(2 * (attempt + 1))
        if k % 20 == 0:
            log(f"[unido] {k}/{len(meta['countries'])}개국")
        time.sleep(0.2)
    df = pd.DataFrame(rows, columns=["iso3", "year", "value"])
    return df.groupby(["iso3", "year"], as_index=False)["value"].sum()


WDI_MIRROR = "https://raw.githubusercontent.com/datasets/world-development-indicators/master/indicators/{code}/data.csv"


def fetch_wdi_mirror(code: str, years: list[int], log=print) -> pd.DataFrame:
    """세계은행 WDI 한 지표(GitHub 미러 CSV: Country Name, Country Code, Year, Value)."""
    import io

    import requests

    log(f"[external] WDI 미러 {code}")
    r = requests.get(WDI_MIRROR.format(code=code), timeout=60)
    r.raise_for_status()
    d = pd.read_csv(io.StringIO(r.text)).rename(columns={"Country Code": "iso3", "Year": "year", "Value": "value"})
    d = d[d.year.isin(years)][["iso3", "year", "value"]].dropna()
    return d.astype({"iso3": str, "year": int, "value": float})


def korea_fta_years(years: list[int], cap: int = 10) -> pd.DataFrame:
    import yaml

    cfg = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "sources" / "korea_fta.yaml").read_text())
    start = {}
    for g in cfg["groups"].values():
        for c in g["iso3"]:
            start[c] = min(start.get(c, 9999), g["year"])
    cpath = Path(__file__).resolve().parents[2] / "data" / "store" / "countries.csv"
    allc = set(pd.read_csv(cpath).iso3) if cpath.exists() else set()
    rows = [(c, y, float(min(cap, max(0, y - start[c] + 1)) if c in start else 0.0))
            for c in sorted(allc | set(start)) for y in years]
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
    if spec["kind"] == "unido":
        log(f"[external] UNIDO {name}: {len(years)}개 연도, 국가별 호출")
        return fetch_unido(spec, years, log)
    if spec["kind"] == "wdi_mirror":
        return fetch_wdi_mirror(spec["code"], years, log)
    if spec["kind"] == "korea_fta":
        return korea_fta_years(years)
    if spec["kind"] == "file":
        df = _file(spec, years)
        if df is None:
            log(f"[external] {name}: 파일 없음 → {RAW / spec['file']} ({spec.get('how', '')})")
        return df
    raise ValueError(spec["kind"])
