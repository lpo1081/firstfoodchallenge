[1/4] 가설 검증 에이전트 반영과 실행 완료 (09:15 KST). 중요한 데이터 문제가 있어 먼저 적습니다.

■ ⚠ 구글 트렌드 데이터가 사실상 쓸 수 없는 상태입니다
data/store/external/gtrends_kpop.csv를 보면 모든 국가·연도 값이 0 아니면 100입니다(2018년 기준 100이 177개국, 0이 39개국). pytrends의 interest_by_region(inc_low_vol=True, 키워드 2개 합산)이 지금 이런 값을 돌려주고 있어서, 관심도의 크기가 아니라 "검색 데이터가 있느냐 없느냐"만 담겨 있습니다. kfood, learnkorean도 같습니다.
그 결과 분석 창 안에서:
- kpop_interest와 kpop_interest_change는 2016년 이후 모든 국가가 같은 값이라 정보가 0입니다(redundancy rho가 NaN으로 나온 이유).
- kfood_interest는 고유값이 2~4개, learn_korean_interest는 2021년에 고유값 1개입니다.
따라서 kculture 가설의 '채택'과 adopt에서 kfood_interest를 추가한 결정은 실질적으로 신뢰할 수 없습니다. 실제 데이터에 기반해 의미가 있는 건 korea_visitors_pc(방한객, KTO)뿐이고, abs 정답 기준 단독 투입에서 채택(+0.054, 우위 99%), log 정답 기준에서는 보류(+0.019, 93%)였습니다.
k_export_agent.yaml은 그대로 생성돼 있지만(kfood_interest 포함) 이 문제 때문에 쓰지 않기를 권합니다. 파일 삭제는 하지 않았습니다.
고칠 방법을 확인하려 했지만 지금 구글이 429를 반환해서 재현 테스트를 못 했습니다. 키워드를 하나씩 따로 요청하거나, 연도별 국가 비교 대신 interest_over_time을 국가별로 받는 방식이 필요해 보입니다.

■ 이 PC에서 한 작업
- 백업: ~/kfood_scout_backup_agent_202611030851.tgz (data/cache와 .venv 제외)
- config.py(series_key external), store.py(external_series, needs ex, assemble_panel EX): 지시대로 수정
- 새 파일: agent/*, sources/external.py, config/hypotheses/kculture.yaml, tests/test_agent.py (원문 그대로)
- pip install pytrends anthropic. pytest -q tests: 6 passed
- 추가 수정 1: external.py의 TrendReq(hl, tz, retries=3, backoff_factor=2)를 TrendReq(hl="en-US", tz=0)로 변경. retries 옵션이 urllib3 2.x에서 'method_whitelist' 오류를 내서 첫 실행이 전부 실패했습니다. 재시도는 기존 루프(5회, 30초×n 대기)가 맡습니다. 첫 실행 로그는 agent_try1.log로 보관했고, 그때는 LLM 호출 전에 중단했습니다.
- 추가 수정 2: fetch_kto_visitors 구현(약 15분 소요). know.tour.go.kr/stat/entryTourStatDis_DataXML.do에 searchDivision=entryNationality, 연간, 2005–2024를 POST하면 국적별 XML이 옵니다. 대륙합계·기타·미상·교포(코드 1, 997, 999)는 제외했고, 59개국 모두 매핑했습니다(못 맞춘 이름 0개). 원본은 data/external/raw/kto_visitors_raw.xml
- 실행 순서: scripts/agent_run.sh (test abs → test log → loop 2라운드 → adopt → report), nohup + caffeinate. ANTHROPIC_API_KEY 인식됨(값 출력 없음). LLM 호출은 2회였고 모두 정상 응답
- 참고: test(log)가 test(abs) 뒤에 실행되면서 outputs/agent/dry_confectionery/kculture.json이 log 결과로 덮어써졌습니다. abs 결과는 ledger.jsonl과 report에만 남아 있습니다. adopt는 마지막(log) 결과의 단독 판정(kfood_interest weak, korea_visitors_pc weak)으로 두 지표를 추가했습니다.
- 참고: 2라운드 가설 id가 auto_auto_…로 접두사가 두 번 붙었습니다(LLM이 id에 auto_를 넣음)

■ data/store/external/*.csv 요약
- gtrends_kfood.csv: 4,320행, 216개국 × 2005–2024 매년 216개국. 값이 0보다 큰 나라 수: 2005년 17, 2010년 38, 2015년 97, 2020년 119, 2024년 127
- gtrends_kpop.csv: 4,320행, 216개국 매년. 값이 0보다 큰 나라: 23 / 71 / 160 / 190 / 193 (값은 0 또는 100뿐)
- gtrends_learnkorean.csv: 4,320행, 216개국 매년. 값이 0보다 큰 나라: 26 / 58 / 104 / 133 / 137
- kto_visitors.csv: 1,180행, 59개국 × 2005–2024 매년 59개국 (대만 TWN 포함. TWN은 WB 국가 목록에 없어 분석에서는 빠짐)

■ report 출력 전문 (python -m kfood_scout.agent report)
# 에이전트 검증 기록 (dry_confectionery)

| 시각 | 가설 | 제안 | 판정 | 표본 밖 개선 | 우위 확률 |
|---|---|---|---|---|---|
| 2026-11-03T09:10:42 | kculture | human (형님) | 채택 | +0.059 | 100% |
| 2026-11-03T09:10:57 | kculture | human (형님) | 채택 | +0.029 | 90% |
| 2026-11-03T09:11:50 | auto_korea_human_network | llm:claude-opus-5-5 | 데이터 필요 | - | - |
| 2026-11-03T09:11:58 | auto_food_import_dependence | llm:claude-opus-5-5 | 기각 | -0.032 | 1% |
| 2026-11-03T09:12:06 | auto_digital_adoption_speed | llm:claude-opus-5-5 | 기각 | -0.016 | 15% |
| 2026-11-03T09:13:06 | auto_auto_migrant_population | llm:claude-opus-5-5 | 기각 | -0.019 | 19% |
| 2026-11-03T09:15:31 | auto_auto_reexport_hub | llm:claude-opus-5-5 | 기각 | -0.005 | 32% |
| 2026-11-03T09:15:39 | auto_auto_korea_people_flow_growth | llm:claude-opus-5-5 | 보류 | +0.013 | 81% |
| 2026-11-03T09:15:45 | adopt |  | 모델 갱신 | - | - |

## 판정 근거

### kculture — 채택
신흥국의 소득 성장과 별개로, 한류(K-문화) 확산이 큰 나라일수록 이후 3년간 한국 과자 수출이 더 늘었다.

```
[채택] 표본 밖 7개 구간에서 순위상관이 평균 +0.059 변했고, 국가를 다시 뽑아 본 부트스트랩의 100%에서 기존 모델보다 나았다 (90% 구간 +0.025 ~ +0.096).
kpop_interest: 소득·시장 규모를 통제한 편상관 평균 +0.04 (앞 시기 +0.10 → 최근 -0.02); 가중치 0.05 → 0.07.
kpop_interest_change: 소득·시장 규모를 통제한 편상관 평균 -0.10 (앞 시기 -0.17 → 최근 -0.02); 가중치 0.02 → 0.06.
kfood_interest: 소득·시장 규모를 통제한 편상관 평균 +0.19 (앞 시기 +0.21 → 최근 +0.16); 가중치 0.06 → 0.05.
korea_visitors_pc: 소득·시장 규모를 통제한 편상관 평균 +0.26 (앞 시기 +0.24 → 최근 +0.29); 가중치 0.15 → 0.03.
learn_korean_interest: 소득·시장 규모를 통제한 편상관 평균 +0.16 (앞 시기 +0.21 → 최근 +0.11); 가중치 0.12 → 0.06.
  단독 투입 kpop_interest: weak (평균 +0.002, 우위 64%)
  단독 투입 kpop_interest_change: rejected (평균 -0.001, 우위 39%)
  단독 투입 kfood_interest: weak (평균 +0.008, 우위 85%)
  단독 투입 korea_visitors_pc: accepted (평균 +0.054, 우위 99%)
  단독 투입 learn_korean_interest: weak (평균 +0.006, 우위 72%)
```

### kculture — 채택
신흥국의 소득 성장과 별개로, 한류(K-문화) 확산이 큰 나라일수록 이후 3년간 한국 과자 수출이 더 늘었다.

```
[채택] 표본 밖 7개 구간에서 순위상관이 평균 +0.029 변했고, 국가를 다시 뽑아 본 부트스트랩의 90%에서 기존 모델보다 나았다 (90% 구간 -0.007 ~ +0.062).
kpop_interest: 소득·시장 규모를 통제한 편상관 평균 +0.08 (앞 시기 +0.18 → 최근 -0.02); 가중치 0.08 → 0.08.
kpop_interest_change: 소득·시장 규모를 통제한 편상관 평균 -0.12 (앞 시기 -0.22 → 최근 -0.02); 가중치 0.01 → 0.05.
kfood_interest: 소득·시장 규모를 통제한 편상관 평균 +0.26 (앞 시기 +0.31 → 최근 +0.21); 가중치 0.09 → 0.07.
korea_visitors_pc: 소득·시장 규모를 통제한 편상관 평균 +0.10 (앞 시기 +0.13 → 최근 +0.07); 가중치 0.15 → 0.03.
learn_korean_interest: 소득·시장 규모를 통제한 편상관 평균 +0.20 (앞 시기 +0.27 → 최근 +0.13); 가중치 0.12 → 0.04.
  단독 투입 kpop_interest: rejected (평균 -0.009, 우위 9%)
  단독 투입 kpop_interest_change: rejected (평균 -0.002, 우위 44%)
  단독 투입 kfood_interest: weak (평균 +0.018, 우위 91%)
  단독 투입 korea_visitors_pc: weak (평균 +0.019, 우위 93%)
  단독 투입 learn_korean_interest: rejected (평균 -0.002, 우위 42%)
```

### auto_korea_human_network — 데이터 필요
한국에 장기 체류하는 노동자·유학생과 현지 한인 동포 같은 인적 연결망이 두텁고, 해외 송금 유입이 큰 나라일수록 이후 3년간 한국 과자 수출이 더 늘어난다.

```
미등록 외부 원천 moj_foreign_residents (new_source_needed: (1) moj_foreign_residents: 법무부 「출입국·외국인정책 통계연보」 국적별 체류외국인 수(연간, 2005~). 공공데이터포털(data.go.kr) 또는 법무부 출입국·외국인정책본부 통계에서 국적별 연말 체류자 표를 받아 iso3,year,value CSV로 변환한다. (2) mofa_overseas_koreans: 외교부 「재외동포현황」 국가별 재외동포 수(격년 발간). 외교부 누리집 PDF 또는 공공데이터포털 파일에서 받아 iso3,year,value CSV로 변환하고, 빠진 해는 직전 값으로 채운다.)
```

### auto_food_import_dependence — 기각
자국 식품 생산 기반이 약해 식품을 수입에 크게 의존하고, 1인당 수입 구매 수준이 높은 나라일수록 이후 3년간 한국 과자 수출이 더 늘어난다.

```
[기각] 표본 밖 7개 구간에서 순위상관이 평균 -0.032 변했고, 국가를 다시 뽑아 본 부트스트랩의 1%에서 기존 모델보다 나았다 (90% 구간 -0.057 ~ -0.008).
food_import_share_merch: 소득·시장 규모를 통제한 편상관 평균 -0.10 (앞 시기 -0.05 → 최근 -0.15); 가중치 0.02 → 0.02.
import_pc_level: 소득·시장 규모를 통제한 편상관 평균 -0.03 (앞 시기 -0.00 → 최근 -0.06); 가중치 0.07 → 0.05.
  주의: gdp_pc_ppp와 순위상관 0.82로 정보가 겹침.
  단독 투입 food_import_share_merch: rejected (평균 -0.022, 우위 2%)
  단독 투입 import_pc_level: rejected (평균 -0.004, 우위 35%)
```

### auto_digital_adoption_speed — 기각
인터넷 보급률이 빠르게 오르는 나라일수록 SNS를 통한 해외 간식 유행과 온라인 유통 확산이 일어나, 이후 3년간 한국 과자 수출이 더 늘어난다.

```
[기각] 표본 밖 7개 구간에서 순위상관이 평균 -0.016 변했고, 국가를 다시 뽑아 본 부트스트랩의 15%에서 기존 모델보다 나았다 (90% 구간 -0.044 ~ +0.009).
internet_users_change: 소득·시장 규모를 통제한 편상관 평균 -0.08 (앞 시기 -0.30 → 최근 +0.14); 가중치 0.02 → 0.08.
broadband_change: 소득·시장 규모를 통제한 편상관 평균 -0.07 (앞 시기 -0.05 → 최근 -0.08); 가중치 0.03 → 0.03.
  단독 투입 internet_users_change: weak (평균 +0.012, 우위 92%)
  단독 투입 broadband_change: rejected (평균 -0.022, 우위 8%)
```

### auto_auto_migrant_population — 기각
외국 출신 이주민이 인구에서 차지하는 비중이 크고 순유입이 많은 나라일수록, 소득·시장 규모와 별개로 이후 3년간 한국 과자 수출이 더 늘어난다.

```
[기각] 표본 밖 7개 구간에서 순위상관이 평균 -0.019 변했고, 국가를 다시 뽑아 본 부트스트랩의 19%에서 기존 모델보다 나았다 (90% 구간 -0.058 ~ +0.023).
migrant_stock_share: 소득·시장 규모를 통제한 편상관 평균 -0.07 (앞 시기 -0.06 → 최근 -0.07); 가중치 0.05 → 0.05.
  주의: gdp_pc_ppp와 순위상관 0.78로 정보가 겹침.
net_migration_pc: 소득·시장 규모를 통제한 편상관 평균 +0.13 (앞 시기 +0.11 → 최근 +0.15); 가중치 0.06 → 0.10.
  단독 투입 migrant_stock_share: rejected (평균 -0.021, 우위 2%)
  단독 투입 net_migration_pc: rejected (평균 +0.001, 우위 52%)
```

### auto_auto_reexport_hub — 기각
같은 품목을 다시 수출(재수출)하는 규모가 큰 유통·물류 허브 국가일수록, 자국 소비와 별개로 주변 시장으로 나가는 물량이 붙어 이후 3년간 한국 과자 수출이 더 늘어난다.

```
[기각] 표본 밖 7개 구간에서 순위상관이 평균 -0.005 변했고, 국가를 다시 뽑아 본 부트스트랩의 32%에서 기존 모델보다 나았다 (90% 구간 -0.025 ~ +0.013).
partner_exports_size: 소득·시장 규모를 통제한 편상관 평균 +0.04 (앞 시기 +0.06 → 최근 +0.03); 가중치 0.07 → 0.10.
  주의: import_market_size와 순위상관 0.83로 정보가 겹침.
partner_exports_pc: 소득·시장 규모를 통제한 편상관 평균 -0.06 (앞 시기 -0.01 → 최근 -0.12); 가중치 0.07 → 0.05.
  주의: gdp_pc_ppp와 순위상관 0.80로 정보가 겹침.
  단독 투입 partner_exports_size: weak (평균 +0.011, 우위 87%)
  단독 투입 partner_exports_pc: rejected (평균 +0.001, 우위 54%)
```

### auto_auto_korea_people_flow_growth — 보류
한국을 오가는 사람의 수가 빠르게 늘고, 해외 근로 송금 의존도가 높은 나라일수록 이후 3년간 한국 과자 수출이 더 늘어난다.

```
[보류(약한 개선)] 표본 밖 7개 구간에서 순위상관이 평균 +0.013 변했고, 국가를 다시 뽑아 본 부트스트랩의 81%에서 기존 모델보다 나았다 (90% 구간 -0.010 ~ +0.034).
korea_visitors_cagr: 소득·시장 규모를 통제한 편상관 평균 +0.02 (앞 시기 +0.02 → 최근 +0.02); 가중치 0.07 → 0.04.
remittance_inflow_gdp: 소득·시장 규모를 통제한 편상관 평균 -0.02 (앞 시기 -0.04 → 최근 +0.01); 가중치 0.04 → 0.10.
  단독 투입 korea_visitors_cagr: rejected (평균 +0.001, 우위 50%)
  단독 투입 remittance_inflow_gdp: weak (평균 +0.012, 우위 91%)
```

### adopt — 모델 갱신


```
추가 ['kfood_interest', 'korea_visitors_pc'], 제거 [], 기존 대비 표본 밖 0.06014285714285715
```

(이어서 [2/4] 수정한 external.py 전문과 JSON들, [3/4] 가설 YAML과 k_export_agent.yaml, [4/4] 프롬프트 원문을 보냅니다)


[2/4] 수정한 sources/external.py 전문과 outputs/agent/dry_confectionery/*.json 전문 (JSON은 공백만 뺀 compact이고 내용은 원본과 같음. 원본에는 rho가 NaN으로 들어가 있어 엄격한 JSON 파서로는 안 읽힙니다)

### kfood_scout/sources/external.py
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


def catalog() -> list[dict]:
    out = []
    for name, s in SOURCES.items():
        ready = s["kind"] in ("gtrends", "kto") or (RAW / s["file"]).exists()
        out.append({"series": name, "desc": s["desc"], "kind": s["kind"], "ready": ready, "how": s.get("how", "")})
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
    rows = []
    for y in years:
        if y < 2004:
            continue
        for attempt in range(5):
            try:
                py.build_payload(keywords, timeframe=f"{y}-01-01 {y}-12-31")
                df = py.interest_by_region(resolution="COUNTRY", inc_low_vol=True, inc_geo_code=True)
                break
            except Exception as e:  # noqa: BLE001
                log(f"[gtrends] {keywords} {y} 재시도 {attempt + 1}: {e}")
                time.sleep(30 * (attempt + 1))
        else:
            raise RuntimeError(f"구글 트렌드 수집 실패: {keywords} {y}")
        val = df[keywords].sum(axis=1)
        for code, v in zip(df["geoCode"], val):
            if code in iso:
                rows.append((iso[code], y, float(v)))
        time.sleep(5)
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

### kculture.json (주의: test --target-kind log 결과로 덮어써진 상태)
{"hypothesis":"kculture","statement":"신흥국의 소득 성장과 별개로, 한류(K-문화) 확산이 큰 나라일수록 이후 3년간 한국 과자 수출이 더 늘었다.","category":"dry_confectionery","status":"accepted","rules":{"accept_delta":0.02,"accept_p":0.8,"weak_p":0.6},"coverage":{"kpop_interest":216,"kpop_interest_change":216,"kfood_interest":216,"korea_visitors_pc":58,"learn_korean_interest":216},"data_needed":[],"windows":[2012,2013,2014,2015,2016,2017,2018,2019,2020,2021],"oos_pairs":[{"fit":2012,"test":2015,"n":54,"base":0.108,"aug":0.198,"delta":0.09},{"fit":2013,"test":2016,"n":50,"base":0.109,"aug":0.123,"delta":0.014},{"fit":2014,"test":2017,"n":50,"base":0.316,"aug":0.393,"delta":0.077},{"fit":2015,"test":2018,"n":55,"base":0.356,"aug":0.357,"delta":0.001},{"fit":2016,"test":2019,"n":54,"base":0.32,"aug":0.331,"delta":0.011},{"fit":2017,"test":2020,"n":57,"base":0.171,"aug":0.173,"delta":0.002},{"fit":2018,"test":2021,"n":57,"base":0.135,"aug":0.143,"delta":0.008}],"oos":{"mean_delta":0.029,"p_better":0.902,"ci90":[-0.0070431571768119145,0.0623477513067773]},"candidate_weights":{"2012":{"kpop_interest":0.076,"kpop_interest_change":0.015,"kfood_interest":0.092,"korea_visitors_pc":0.152,"learn_korean_interest":0.122},"2013":{"kpop_interest":0.049,"kpop_interest_change":0.017,"kfood_interest":0.081,"korea_visitors_pc":0.118,"learn_korean_interest":0.109},"2014":{"kpop_interest":0.058,"kpop_interest_change":0.035,"kfood_interest":0.205,"korea_visitors_pc":0.064,"learn_korean_interest":0.058},"2015":{"kpop_interest":0.07,"kpop_interest_change":0.033,"kfood_interest":0.229,"korea_visitors_pc":0.103,"learn_korean_interest":0.053},"2016":{"kpop_interest":0.052,"kpop_interest_change":0.046,"kfood_interest":0.102,"korea_visitors_pc":0.082,"learn_korean_interest":0.035},"2017":{"kpop_interest":0.047,"kpop_interest_change":0.057,"kfood_interest":0.157,"korea_visitors_pc":0.075,"learn_korean_interest":0.117},"2018":{"kpop_interest":0.058,"kpop_interest_change":0.068,"kfood_interest":0.087,"korea_visitors_pc":0.037,"learn_korean_interest":0.058},"2019":{"kpop_interest":0.063,"kpop_interest_change":0.057,"kfood_interest":0.04,"korea_visitors_pc":0.1,"learn_korean_interest":0.044},"2020":{"kpop_interest":0.051,"kpop_interest_change":0.065,"kfood_interest":0.088,"korea_visitors_pc":0.047,"learn_korean_interest":0.042},"2021":{"kpop_interest":0.08,"kpop_interest_change":0.049,"kfood_interest":0.066,"korea_visitors_pc":0.029,"learn_korean_interest":0.044}},"partial_corr":{"kpop_interest":{"2012":0.322,"2013":0.113,"2014":0.224,"2015":0.235,"2016":0.028,"2017":-0.001,"2018":0.009,"2019":-0.012,"2020":-0.058,"2021":-0.021},"kpop_interest_change":{"2012":-0.386,"2013":-0.326,"2014":-0.122,"2015":-0.318,"2016":0.028,"2017":-0.001,"2018":0.009,"2019":-0.012,"2020":-0.058,"2021":-0.021},"kfood_interest":{"2012":0.431,"2013":0.32,"2014":0.372,"2015":0.338,"2016":0.094,"2017":0.407,"2018":0.188,"2019":-0.03,"2020":0.231,"2021":0.259},"korea_visitors_pc":{"2012":0.344,"2013":0.275,"2014":0.064,"2015":-0.025,"2016":-0.023,"2017":0.097,"2018":0.072,"2019":0.124,"2020":0.133,"2021":-0.068},"learn_korean_interest":{"2012":0.493,"2013":0.35,"2014":0.249,"2015":0.213,"2016":0.041,"2017":0.348,"2018":0.182,"2019":0.053,"2020":0.067,"2021":-0.021}},"redundancy":{"kpop_interest":{"most_similar":"import_market_size","rho":NaN},"kpop_interest_change":{"most_similar":"import_market_size","rho":NaN},"kfood_interest":{"most_similar":"hh_consumption_pc_cagr","rho":0.226},"korea_visitors_pc":{"most_similar":"korea_exports_size","rho":0.589},"learn_korean_interest":{"most_similar":"import_market_size","rho":NaN}},"solo":{"kpop_interest":{"status":"rejected","oos":{"mean_delta":-0.008857142857142857,"p_better":0.09,"ci90":[-0.019444447823123236,0.001667845659752085]},"partial_corr":{"kpop_interest":{"2012":0.314,"2013":0.127,"2014":0.224,"2015":0.235,"2016":0.023,"2017":0.067,"2018":0.009,"2019":-0.012,"2020":-0.058,"2021":-0.021}},"redundancy":{"kpop_interest":{"most_similar":"import_market_size","rho":NaN}}},"kpop_interest_change":{"status":"rejected","oos":{"mean_delta":-0.0015714285714285713,"p_better":0.442,"ci90":[-0.012510927103572473,0.009412101733481395]},"partial_corr":{"kpop_interest_change":{"2012":-0.419,"2013":-0.298,"2014":-0.122,"2015":-0.318,"2016":0.023,"2017":0.067,"2018":0.009,"2019":-0.012,"2020":-0.058,"2021":-0.021}},"redundancy":{"kpop_interest_change":{"most_similar":"import_market_size","rho":NaN}}},"kfood_interest":{"status":"weak","oos":{"mean_delta":0.01757142857142857,"p_better":0.912,"ci90":[-0.0029194291272558134,0.03721342755373493]},"partial_corr":{"kfood_interest":{"2012":0.447,"2013":0.284,"2014":0.372,"2015":0.338,"2016":0.004,"2017":0.377,"2018":0.188,"2019":-0.03,"2020":0.231,"2021":0.259}},"redundancy":{"kfood_interest":{"most_similar":"hh_consumption_pc_cagr","rho":0.226}}},"korea_visitors_pc":{"status":"weak","oos":{"mean_delta":0.01871428571428571,"p_better":0.93,"ci90":[-0.0017999959463835412,0.04157035736373593]},"partial_corr":{"korea_visitors_pc":{"2012":0.331,"2013":0.284,"2014":0.064,"2015":-0.025,"2016":0.0,"2017":0.116,"2018":0.073,"2019":0.124,"2020":0.133,"2021":-0.068}},"redundancy":{"korea_visitors_pc":{"most_similar":"korea_exports_size","rho":0.589}}},"learn_korean_interest":{"status":"rejected","oos":{"mean_delta":-0.002142857142857142,"p_better":0.418,"ci90":[-0.02129150516399356,0.016816074158396487]},"partial_corr":{"learn_korean_interest":{"2012":0.495,"2013":0.318,"2014":0.249,"2015":0.213,"2016":-0.075,"2017":0.31,"2018":0.182,"2019":0.053,"2020":0.067,"2021":-0.021}},"redundancy":{"learn_korean_interest":{"most_similar":"import_market_size","rho":NaN}}}},"reason":"[채택] 표본 밖 7개 구간에서 순위상관이 평균 +0.029 변했고, 국가를 다시 뽑아 본 부트스트랩의 90%에서 기존 모델보다 나았다 (90% 구간 -0.007 ~ +0.062).\nkpop_interest: 소득·시장 규모를 통제한 편상관 평균 +0.08 (앞 시기 +0.18 → 최근 -0.02); 가중치 0.08 → 0.08.\nkpop_interest_change: 소득·시장 규모를 통제한 편상관 평균 -0.12 (앞 시기 -0.22 → 최근 -0.02); 가중치 0.01 → 0.05.\nkfood_interest: 소득·시장 규모를 통제한 편상관 평균 +0.26 (앞 시기 +0.31 → 최근 +0.21); 가중치 0.09 → 0.07.\nkorea_visitors_pc: 소득·시장 규모를 통제한 편상관 평균 +0.10 (앞 시기 +0.13 → 최근 +0.07); 가중치 0.15 → 0.03.\nlearn_korean_interest: 소득·시장 규모를 통제한 편상관 평균 +0.20 (앞 시기 +0.27 → 최근 +0.13); 가중치 0.12 → 0.04.\n  단독 투입 kpop_interest: rejected (평균 -0.009, 우위 9%)\n  단독 투입 kpop_interest_change: rejected (평균 -0.002, 우위 44%)\n  단독 투입 kfood_interest: weak (평균 +0.018, 우위 91%)\n  단독 투입 korea_visitors_pc: weak (평균 +0.019, 우위 93%)\n  단독 투입 learn_korean_interest: rejected (평균 -0.002, 우위 42%)","target_kind":"log"}

### adopt.json
{"added":["kfood_interest","korea_visitors_pc"],"dropped":[],"mean_weights":{"import_market_size":0.153,"import_market_cagr":0.033,"hh_consumption_pc_cagr":0.048,"population_size":0.071,"youth_share":0.049,"urbanization_change":0.057,"gdp_pc_ppp":0.109,"import_pc_cagr":0.035,"korea_exports_size":0.074,"korea_exports_cagr":0.037,"korea_share":0.034,"korea_share_change":0.051,"kfood_interest":0.104,"korea_visitors_pc":0.145},"oos_vs_base":{"mean_delta":0.06014285714285715,"p_better":1.0,"ci90":[0.02604903719666194,0.09325381281573902]},"oos_pairs":[{"fit":2012,"test":2015,"n":54,"base":0.191,"aug":0.26,"delta":0.07},{"fit":2013,"test":2016,"n":50,"base":0.286,"aug":0.318,"delta":0.032},{"fit":2014,"test":2017,"n":50,"base":0.245,"aug":0.291,"delta":0.046},{"fit":2015,"test":2018,"n":55,"base":0.488,"aug":0.546,"delta":0.058},{"fit":2016,"test":2019,"n":54,"base":0.499,"aug":0.582,"delta":0.082},{"fit":2017,"test":2020,"n":57,"base":0.267,"aug":0.367,"delta":0.1},{"fit":2018,"test":2021,"n":57,"base":0.352,"aug":0.385,"delta":0.033}],"written":true}

### auto_food_import_dependence.json
{"hypothesis":"auto_food_import_dependence","statement":"자국 식품 생산 기반이 약해 식품을 수입에 크게 의존하고, 1인당 수입 구매 수준이 높은 나라일수록 이후 3년간 한국 과자 수출이 더 늘어난다.","category":"dry_confectionery","status":"rejected","rules":{"accept_delta":0.02,"accept_p":0.8,"weak_p":0.6},"coverage":{"food_import_share_merch":216,"import_pc_level":174},"data_needed":[],"windows":[2012,2013,2014,2015,2016,2017,2018,2019,2020,2021],"oos_pairs":[{"fit":2012,"test":2015,"n":54,"base":0.191,"aug":0.205,"delta":0.014},{"fit":2013,"test":2016,"n":50,"base":0.286,"aug":0.27,"delta":-0.016},{"fit":2014,"test":2017,"n":50,"base":0.245,"aug":0.258,"delta":0.013},{"fit":2015,"test":2018,"n":55,"base":0.488,"aug":0.483,"delta":-0.005},{"fit":2016,"test":2019,"n":54,"base":0.499,"aug":0.335,"delta":-0.165},{"fit":2017,"test":2020,"n":57,"base":0.267,"aug":0.212,"delta":-0.055},{"fit":2018,"test":2021,"n":57,"base":0.352,"aug":0.341,"delta":-0.011}],"oos":{"mean_delta":-0.03214285714285715,"p_better":0.014,"ci90":[-0.05650605194910389,-0.008076464967468057]},"candidate_weights":{"2012":{"food_import_share_merch":0.016,"import_pc_level":0.071},"2013":{"food_import_share_merch":0.019,"import_pc_level":0.095},"2014":{"food_import_share_merch":0.026,"import_pc_level":0.343},"2015":{"food_import_share_merch":0.066,"import_pc_level":0.122},"2016":{"food_import_share_merch":0.134,"import_pc_level":0.052},"2017":{"food_import_share_merch":0.079,"import_pc_level":0.099},"2018":{"food_import_share_merch":0.014,"import_pc_level":0.104},"2019":{"food_import_share_merch":0.013,"import_pc_level":0.093},"2020":{"food_import_share_merch":0.015,"import_pc_level":0.04},"2021":{"food_import_share_merch":0.021,"import_pc_level":0.054}},"partial_corr":{"food_import_share_merch":{"2012":-0.211,"2013":-0.186,"2014":-0.074,"2015":0.033,"2016":0.188,"2017":0.098,"2018":-0.212,"2019":-0.284,"2020":-0.242,"2021":-0.121},"import_pc_level":{"2012":-0.193,"2013":-0.124,"2014":0.185,"2015":0.145,"2016":-0.037,"2017":0.137,"2018":0.074,"2019":-0.139,"2020":-0.23,"2021":-0.143}},"redundancy":{"food_import_share_merch":{"most_similar":"youth_share","rho":0.48},"import_pc_level":{"most_similar":"gdp_pc_ppp","rho":0.821}},"solo":{"food_import_share_merch":{"status":"rejected","oos":{"mean_delta":-0.022285714285714287,"p_better":0.022,"ci90":[-0.043419219462963836,-0.004893687268248056]},"partial_corr":{"food_import_share_merch":{"2012":-0.211,"2013":-0.186,"2014":-0.074,"2015":0.033,"2016":0.188,"2017":0.098,"2018":-0.212,"2019":-0.284,"2020":-0.242,"2021":-0.121}},"redundancy":{"food_import_share_merch":{"most_similar":"youth_share","rho":0.48}}},"import_pc_level":{"status":"rejected","oos":{"mean_delta":-0.004428571428571428,"p_better":0.35,"ci90":[-0.025018514802419435,0.014500917275502104]},"partial_corr":{"import_pc_level":{"2012":-0.193,"2013":-0.124,"2014":0.185,"2015":0.145,"2016":-0.037,"2017":0.137,"2018":0.074,"2019":-0.139,"2020":-0.23,"2021":-0.143}},"redundancy":{"import_pc_level":{"most_similar":"gdp_pc_ppp","rho":0.821}}}},"reason":"[기각] 표본 밖 7개 구간에서 순위상관이 평균 -0.032 변했고, 국가를 다시 뽑아 본 부트스트랩의 1%에서 기존 모델보다 나았다 (90% 구간 -0.057 ~ -0.008).\nfood_import_share_merch: 소득·시장 규모를 통제한 편상관 평균 -0.10 (앞 시기 -0.05 → 최근 -0.15); 가중치 0.02 → 0.02.\nimport_pc_level: 소득·시장 규모를 통제한 편상관 평균 -0.03 (앞 시기 -0.00 → 최근 -0.06); 가중치 0.07 → 0.05.\n  주의: gdp_pc_ppp와 순위상관 0.82로 정보가 겹침.\n  단독 투입 food_import_share_merch: rejected (평균 -0.022, 우위 2%)\n  단독 투입 import_pc_level: rejected (평균 -0.004, 우위 35%)","target_kind":"abs"}

### auto_digital_adoption_speed.json
{"hypothesis":"auto_digital_adoption_speed","statement":"인터넷 보급률이 빠르게 오르는 나라일수록 SNS를 통한 해외 간식 유행과 온라인 유통 확산이 일어나, 이후 3년간 한국 과자 수출이 더 늘어난다.","category":"dry_confectionery","status":"rejected","rules":{"accept_delta":0.02,"accept_p":0.8,"weak_p":0.6},"coverage":{"internet_users_change":213,"broadband_change":248},"data_needed":[],"windows":[2012,2013,2014,2015,2016,2017,2018,2019,2020,2021],"oos_pairs":[{"fit":2012,"test":2015,"n":54,"base":0.191,"aug":0.181,"delta":-0.01},{"fit":2013,"test":2016,"n":50,"base":0.286,"aug":0.278,"delta":-0.008},{"fit":2014,"test":2017,"n":50,"base":0.245,"aug":0.232,"delta":-0.013},{"fit":2015,"test":2018,"n":55,"base":0.488,"aug":0.375,"delta":-0.113},{"fit":2016,"test":2019,"n":54,"base":0.499,"aug":0.498,"delta":-0.002},{"fit":2017,"test":2020,"n":57,"base":0.267,"aug":0.271,"delta":0.005},{"fit":2018,"test":2021,"n":57,"base":0.352,"aug":0.378,"delta":0.026}],"oos":{"mean_delta":-0.01642857142857143,"p_better":0.148,"ci90":[-0.043534928651777986,0.009488966064350086]},"candidate_weights":{"2012":{"internet_users_change":0.02,"broadband_change":0.028},"2013":{"internet_users_change":0.015,"broadband_change":0.033},"2014":{"internet_users_change":0.016,"broadband_change":0.076},"2015":{"internet_users_change":0.016,"broadband_change":0.201},"2016":{"internet_users_change":0.036,"broadband_change":0.068},"2017":{"internet_users_change":0.034,"broadband_change":0.024},"2018":{"internet_users_change":0.059,"broadband_change":0.029},"2019":{"internet_users_change":0.032,"broadband_change":0.042},"2020":{"internet_users_change":0.122,"broadband_change":0.034},"2021":{"internet_users_change":0.077,"broadband_change":0.028}},"partial_corr":{"internet_users_change":{"2012":-0.349,"2013":-0.341,"2014":-0.455,"2015":-0.318,"2016":-0.016,"2017":0.014,"2018":0.153,"2019":0.006,"2020":0.366,"2021":0.17},"broadband_change":{"2012":-0.193,"2013":-0.091,"2014":0.073,"2015":0.079,"2016":-0.139,"2017":-0.244,"2018":-0.091,"2019":0.064,"2020":-0.002,"2021":-0.112}},"redundancy":{"internet_users_change":{"most_similar":"gdp_pc_ppp","rho":0.68},"broadband_change":{"most_similar":"import_market_size","rho":0.29}},"solo":{"internet_users_change":{"status":"weak","oos":{"mean_delta":0.012142857142857141,"p_better":0.92,"ci90":[-0.002139798123980687,0.026063768952053694]},"partial_corr":{"internet_users_change":{"2012":-0.347,"2013":-0.381,"2014":-0.455,"2015":-0.318,"2016":0.027,"2017":0.009,"2018":0.153,"2019":0.006,"2020":0.366,"2021":0.17}},"redundancy":{"internet_users_change":{"most_similar":"gdp_pc_ppp","rho":0.68}}},"broadband_change":{"status":"rejected","oos":{"mean_delta":-0.02242857142857143,"p_better":0.078,"ci90":[-0.04765870743896479,0.0026269027432491354]},"partial_corr":{"broadband_change":{"2012":-0.197,"2013":-0.133,"2014":0.073,"2015":0.079,"2016":-0.189,"2017":-0.258,"2018":-0.091,"2019":0.064,"2020":-0.002,"2021":-0.112}},"redundancy":{"broadband_change":{"most_similar":"import_market_size","rho":0.29}}}},"reason":"[기각] 표본 밖 7개 구간에서 순위상관이 평균 -0.016 변했고, 국가를 다시 뽑아 본 부트스트랩의 15%에서 기존 모델보다 나았다 (90% 구간 -0.044 ~ +0.009).\ninternet_users_change: 소득·시장 규모를 통제한 편상관 평균 -0.08 (앞 시기 -0.30 → 최근 +0.14); 가중치 0.02 → 0.08.\nbroadband_change: 소득·시장 규모를 통제한 편상관 평균 -0.07 (앞 시기 -0.05 → 최근 -0.08); 가중치 0.03 → 0.03.\n  단독 투입 internet_users_change: weak (평균 +0.012, 우위 92%)\n  단독 투입 broadband_change: rejected (평균 -0.022, 우위 8%)","target_kind":"abs"}

(나머지 auto JSON 3개는 [3/4]에서 이어서 보냅니다)


[3/4] 나머지 auto JSON 3개, config/hypotheses/auto_*.yaml 전문, config/criteria/k_export_agent.yaml 전문

### auto_auto_migrant_population.json
{"hypothesis":"auto_auto_migrant_population","statement":"외국 출신 이주민이 인구에서 차지하는 비중이 크고 순유입이 많은 나라일수록, 소득·시장 규모와 별개로 이후 3년간 한국 과자 수출이 더 늘어난다.","category":"dry_confectionery","status":"rejected","rules":{"accept_delta":0.02,"accept_p":0.8,"weak_p":0.6},"coverage":{"migrant_stock_share":260,"net_migration_pc":261},"data_needed":[],"windows":[2012,2013,2014,2015,2016,2017,2018,2019,2020,2021],"oos_pairs":[{"fit":2012,"test":2015,"n":54,"base":0.191,"aug":0.168,"delta":-0.023},{"fit":2013,"test":2016,"n":50,"base":0.286,"aug":0.227,"delta":-0.059},{"fit":2014,"test":2017,"n":50,"base":0.245,"aug":0.3,"delta":0.055},{"fit":2015,"test":2018,"n":55,"base":0.488,"aug":0.518,"delta":0.03},{"fit":2016,"test":2019,"n":54,"base":0.499,"aug":0.394,"delta":-0.105},{"fit":2017,"test":2020,"n":57,"base":0.267,"aug":0.236,"delta":-0.031},{"fit":2018,"test":2021,"n":57,"base":0.352,"aug":0.354,"delta":0.001}],"oos":{"mean_delta":-0.018857142857142854,"p_better":0.19,"ci90":[-0.058362526249281656,0.022506068949756475]},"candidate_weights":{"2012":{"migrant_stock_share":0.047,"net_migration_pc":0.061},"2013":{"migrant_stock_share":0.086,"net_migration_pc":0.059},"2014":{"migrant_stock_share":0.068,"net_migration_pc":0.056},"2015":{"migrant_stock_share":0.026,"net_migration_pc":0.055},"2016":{"migrant_stock_share":0.021,"net_migration_pc":0.207},"2017":{"migrant_stock_share":0.028,"net_migration_pc":0.424},"2018":{"migrant_stock_share":0.072,"net_migration_pc":0.157},"2019":{"migrant_stock_share":0.09,"net_migration_pc":0.04},"2020":{"migrant_stock_share":0.031,"net_migration_pc":0.053},"2021":{"migrant_stock_share":0.049,"net_migration_pc":0.098}},"partial_corr":{"migrant_stock_share":{"2012":0.041,"2013":0.042,"2014":0.003,"2015":-0.136,"2016":-0.256,"2017":-0.047,"2018":-0.019,"2019":-0.011,"2020":-0.195,"2021":-0.092},"net_migration_pc":{"2012":0.24,"2013":0.051,"2014":-0.074,"2015":-0.004,"2016":0.342,"2017":0.473,"2018":0.226,"2019":-0.07,"2020":-0.057,"2021":0.164}},"redundancy":{"migrant_stock_share":{"most_similar":"gdp_pc_ppp","rho":0.776},"net_migration_pc":{"most_similar":"gdp_pc_ppp","rho":0.482}},"solo":{"migrant_stock_share":{"status":"rejected","oos":{"mean_delta":-0.021428571428571432,"p_better":0.018,"ci90":[-0.04042129520690868,-0.005636414363484705]},"partial_corr":{"migrant_stock_share":{"2012":0.033,"2013":-0.0,"2014":0.003,"2015":-0.136,"2016":-0.191,"2017":-0.041,"2018":0.035,"2019":-0.011,"2020":-0.195,"2021":-0.092}},"redundancy":{"migrant_stock_share":{"most_similar":"gdp_pc_ppp","rho":0.776}}},"net_migration_pc":{"status":"rejected","oos":{"mean_delta":0.001285714285714284,"p_better":0.524,"ci90":[-0.038157538034487015,0.04138066613255305]},"partial_corr":{"net_migration_pc":{"2012":0.228,"2013":0.051,"2014":-0.074,"2015":-0.004,"2016":0.434,"2017":0.486,"2018":0.226,"2019":-0.07,"2020":-0.057,"2021":0.164}},"redundancy":{"net_migration_pc":{"most_similar":"gdp_pc_ppp","rho":0.482}}}},"reason":"[기각] 표본 밖 7개 구간에서 순위상관이 평균 -0.019 변했고, 국가를 다시 뽑아 본 부트스트랩의 19%에서 기존 모델보다 나았다 (90% 구간 -0.058 ~ +0.023).\nmigrant_stock_share: 소득·시장 규모를 통제한 편상관 평균 -0.07 (앞 시기 -0.06 → 최근 -0.07); 가중치 0.05 → 0.05.\n  주의: gdp_pc_ppp와 순위상관 0.78로 정보가 겹침.\nnet_migration_pc: 소득·시장 규모를 통제한 편상관 평균 +0.13 (앞 시기 +0.11 → 최근 +0.15); 가중치 0.06 → 0.10.\n  단독 투입 migrant_stock_share: rejected (평균 -0.021, 우위 2%)\n  단독 투입 net_migration_pc: rejected (평균 +0.001, 우위 52%)","target_kind":"abs"}

### auto_auto_reexport_hub.json
{"hypothesis":"auto_auto_reexport_hub","statement":"같은 품목을 다시 수출(재수출)하는 규모가 큰 유통·물류 허브 국가일수록, 자국 소비와 별개로 주변 시장으로 나가는 물량이 붙어 이후 3년간 한국 과자 수출이 더 늘어난다.","category":"dry_confectionery","status":"rejected","rules":{"accept_delta":0.02,"accept_p":0.8,"weak_p":0.6},"coverage":{"partner_exports_size":169,"partner_exports_pc":167},"data_needed":[],"windows":[2012,2013,2014,2015,2016,2017,2018,2019,2020,2021],"oos_pairs":[{"fit":2012,"test":2015,"n":54,"base":0.191,"aug":0.192,"delta":0.002},{"fit":2013,"test":2016,"n":50,"base":0.286,"aug":0.239,"delta":-0.047},{"fit":2014,"test":2017,"n":50,"base":0.245,"aug":0.246,"delta":0.001},{"fit":2015,"test":2018,"n":55,"base":0.488,"aug":0.478,"delta":-0.01},{"fit":2016,"test":2019,"n":54,"base":0.499,"aug":0.518,"delta":0.018},{"fit":2017,"test":2020,"n":57,"base":0.267,"aug":0.261,"delta":-0.006},{"fit":2018,"test":2021,"n":57,"base":0.352,"aug":0.357,"delta":0.005}],"oos":{"mean_delta":-0.005285714285714287,"p_better":0.316,"ci90":[-0.025215015025375303,0.013235210733410606]},"candidate_weights":{"2012":{"partner_exports_size":0.066,"partner_exports_pc":0.067},"2013":{"partner_exports_size":0.047,"partner_exports_pc":0.079},"2014":{"partner_exports_size":0.057,"partner_exports_pc":0.187},"2015":{"partner_exports_size":0.113,"partner_exports_pc":0.078},"2016":{"partner_exports_size":0.061,"partner_exports_pc":0.024},"2017":{"partner_exports_size":0.083,"partner_exports_pc":0.071},"2018":{"partner_exports_size":0.057,"partner_exports_pc":0.066},"2019":{"partner_exports_size":0.063,"partner_exports_pc":0.079},"2020":{"partner_exports_size":0.104,"partner_exports_pc":0.047},"2021":{"partner_exports_size":0.097,"partner_exports_pc":0.053}},"partial_corr":{"partner_exports_size":{"2012":0.186,"2013":0.091,"2014":-0.018,"2015":0.038,"2016":-0.007,"2017":-0.077,"2018":-0.051,"2019":0.025,"2020":0.108,"2021":0.138},"partner_exports_pc":{"2012":0.033,"2013":-0.075,"2014":0.044,"2015":0.082,"2016":-0.133,"2017":-0.02,"2018":-0.039,"2019":-0.223,"2020":-0.226,"2021":-0.08}},"redundancy":{"partner_exports_size":{"most_similar":"import_market_size","rho":0.834},"partner_exports_pc":{"most_similar":"gdp_pc_ppp","rho":0.795}},"solo":{"partner_exports_size":{"status":"weak","oos":{"mean_delta":0.011142857142857144,"p_better":0.868,"ci90":[-0.005847192716736894,0.025854006309392587]},"partial_corr":{"partner_exports_size":{"2012":0.186,"2013":0.091,"2014":-0.018,"2015":0.038,"2016":-0.007,"2017":-0.077,"2018":-0.051,"2019":0.025,"2020":0.108,"2021":0.138}},"redundancy":{"partner_exports_size":{"most_similar":"import_market_size","rho":0.834}}},"partner_exports_pc":{"status":"rejected","oos":{"mean_delta":0.0012857142857142859,"p_better":0.542,"ci90":[-0.016566020834680697,0.018667864662118852]},"partial_corr":{"partner_exports_pc":{"2012":0.033,"2013":-0.075,"2014":0.044,"2015":0.082,"2016":-0.133,"2017":-0.02,"2018":-0.039,"2019":-0.223,"2020":-0.226,"2021":-0.08}},"redundancy":{"partner_exports_pc":{"most_similar":"gdp_pc_ppp","rho":0.795}}}},"reason":"[기각] 표본 밖 7개 구간에서 순위상관이 평균 -0.005 변했고, 국가를 다시 뽑아 본 부트스트랩의 32%에서 기존 모델보다 나았다 (90% 구간 -0.025 ~ +0.013).\npartner_exports_size: 소득·시장 규모를 통제한 편상관 평균 +0.04 (앞 시기 +0.06 → 최근 +0.03); 가중치 0.07 → 0.10.\n  주의: import_market_size와 순위상관 0.83로 정보가 겹침.\npartner_exports_pc: 소득·시장 규모를 통제한 편상관 평균 -0.06 (앞 시기 -0.01 → 최근 -0.12); 가중치 0.07 → 0.05.\n  주의: gdp_pc_ppp와 순위상관 0.80로 정보가 겹침.\n  단독 투입 partner_exports_size: weak (평균 +0.011, 우위 87%)\n  단독 투입 partner_exports_pc: rejected (평균 +0.001, 우위 54%)","target_kind":"abs"}

### auto_auto_korea_people_flow_growth.json
{"hypothesis":"auto_auto_korea_people_flow_growth","statement":"한국을 오가는 사람의 수가 빠르게 늘고, 해외 근로 송금 의존도가 높은 나라일수록 이후 3년간 한국 과자 수출이 더 늘어난다.","category":"dry_confectionery","status":"weak","rules":{"accept_delta":0.02,"accept_p":0.8,"weak_p":0.6},"coverage":{"korea_visitors_cagr":59,"remittance_inflow_gdp":223},"data_needed":[],"windows":[2012,2013,2014,2015,2016,2017,2018,2019,2020,2021],"oos_pairs":[{"fit":2012,"test":2015,"n":54,"base":0.191,"aug":0.229,"delta":0.039},{"fit":2013,"test":2016,"n":50,"base":0.286,"aug":0.228,"delta":-0.058},{"fit":2014,"test":2017,"n":50,"base":0.245,"aug":0.257,"delta":0.012},{"fit":2015,"test":2018,"n":55,"base":0.488,"aug":0.491,"delta":0.003},{"fit":2016,"test":2019,"n":54,"base":0.499,"aug":0.536,"delta":0.036},{"fit":2017,"test":2020,"n":57,"base":0.267,"aug":0.274,"delta":0.008},{"fit":2018,"test":2021,"n":57,"base":0.352,"aug":0.403,"delta":0.05}],"oos":{"mean_delta":0.012857142857142857,"p_better":0.812,"ci90":[-0.01028149779695964,0.03374185912441406]},"candidate_weights":{"2012":{"korea_visitors_cagr":0.067,"remittance_inflow_gdp":0.035},"2013":{"korea_visitors_cagr":0.135,"remittance_inflow_gdp":0.026},"2014":{"korea_visitors_cagr":0.041,"remittance_inflow_gdp":0.032},"2015":{"korea_visitors_cagr":0.164,"remittance_inflow_gdp":0.038},"2016":{"korea_visitors_cagr":0.022,"remittance_inflow_gdp":0.034},"2017":{"korea_visitors_cagr":0.105,"remittance_inflow_gdp":0.026},"2018":{"korea_visitors_cagr":0.043,"remittance_inflow_gdp":0.05},"2019":{"korea_visitors_cagr":0.024,"remittance_inflow_gdp":0.047},"2020":{"korea_visitors_cagr":0.029,"remittance_inflow_gdp":0.087},"2021":{"korea_visitors_cagr":0.044,"remittance_inflow_gdp":0.096}},"partial_corr":{"korea_visitors_cagr":{"2012":0.107,"2013":0.315,"2014":-0.135,"2015":0.039,"2016":-0.208,"2017":0.152,"2018":0.059,"2019":-0.185,"2020":0.02,"2021":0.049},"remittance_inflow_gdp":{"2012":-0.046,"2013":-0.137,"2014":0.041,"2015":0.047,"2016":-0.127,"2017":-0.079,"2018":0.005,"2019":-0.051,"2020":0.053,"2021":0.127}},"redundancy":{"korea_visitors_cagr":{"most_similar":"korea_share","rho":0.364},"remittance_inflow_gdp":{"most_similar":"gdp_pc_ppp","rho":0.567}},"solo":{"korea_visitors_cagr":{"status":"rejected","oos":{"mean_delta":0.001285714285714286,"p_better":0.502,"ci90":[-0.022288988450775565,0.024062567079377595]},"partial_corr":{"korea_visitors_cagr":{"2012":0.092,"2013":0.314,"2014":-0.135,"2015":0.039,"2016":-0.208,"2017":0.168,"2018":0.067,"2019":-0.185,"2020":0.02,"2021":0.049}},"redundancy":{"korea_visitors_cagr":{"most_similar":"korea_share","rho":0.364}}},"remittance_inflow_gdp":{"status":"weak","oos":{"mean_delta":0.012142857142857141,"p_better":0.908,"ci90":[-0.0030943416485876233,0.02563567561813236]},"partial_corr":{"remittance_inflow_gdp":{"2012":-0.037,"2013":-0.137,"2014":0.041,"2015":0.047,"2016":-0.127,"2017":-0.079,"2018":0.005,"2019":-0.051,"2020":0.053,"2021":0.127}},"redundancy":{"remittance_inflow_gdp":{"most_similar":"gdp_pc_ppp","rho":0.567}}}},"reason":"[보류(약한 개선)] 표본 밖 7개 구간에서 순위상관이 평균 +0.013 변했고, 국가를 다시 뽑아 본 부트스트랩의 81%에서 기존 모델보다 나았다 (90% 구간 -0.010 ~ +0.034).\nkorea_visitors_cagr: 소득·시장 규모를 통제한 편상관 평균 +0.02 (앞 시기 +0.02 → 최근 +0.02); 가중치 0.07 → 0.04.\nremittance_inflow_gdp: 소득·시장 규모를 통제한 편상관 평균 -0.02 (앞 시기 -0.04 → 최근 +0.01); 가중치 0.04 → 0.10.\n  단독 투입 korea_visitors_cagr: rejected (평균 +0.001, 우위 50%)\n  단독 투입 remittance_inflow_gdp: weak (평균 +0.012, 우위 91%)","target_kind":"abs"}

### config/hypotheses/auto_auto_korea_people_flow_growth.yaml
id: auto_auto_korea_people_flow_growth
statement: 한국을 오가는 사람의 수가 빠르게 늘고, 해외 근로 송금 의존도가 높은 나라일수록 이후 3년간 한국 과자 수출이 더 늘어난다.
rationale: 네팔(실제 26위, 모델 49위)과 케냐는 소득이 매우 낮아 기존 모델에서 하위권이었습니다. 하지만 네팔은 고용허가제를 통한 한국행
  근로자가 급증한 나라입니다. 귀국자와 그 가족은 한국 제품에 대한 친숙도를 국내로 들여오고, 해외 근로 송금은 통계상 소득보다 실제 구매력을 키웁니다.
  기존에 채택된 korea_visitors_pc는 방한객의 '수준'만 보므로, 여기서는 방한객 수의 증가율을 따로 넣어 인적 연결이 막 두꺼워지는
  단계의 나라를 포착하려 합니다. 법무부·외교부 자료가 없어 보류된 인적 연결망 가설 가운데, 지금 바로 받을 수 있는 자료(KTO 방한객, WDI
  송금)만 떼어 먼저 검증하는 성격도 있습니다. 송금 유입 비중은 GDP 대비 값이라 소득 수준과 겹침이 적을 것으로 예상합니다.
group: 소비트렌드
new_source_needed: ''
indicators:
- id: korea_visitors_cagr
  name_ko: 방한 관광객 수 증가율
  group: 소비트렌드
  source: external
  series: kto_visitors
  transform: cagr
  window: 3
  direction: 1
- id: remittance_inflow_gdp
  name_ko: 개인 송금 유입(GDP 대비)
  group: 성장성
  source: worldbank
  series: BX.TRF.PWKR.DT.GD.ZS
  transform: level
  window: 1
  direction: 1
proposed_by: llm:claude-opus-5-5
created: '2026-11-03'

### config/hypotheses/auto_auto_migrant_population.yaml
id: auto_auto_migrant_population
statement: 외국 출신 이주민이 인구에서 차지하는 비중이 크고 순유입이 많은 나라일수록, 소득·시장 규모와 별개로 이후 3년간 한국 과자 수출이
  더 늘어난다.
rationale: 모델이 크게 놓친 싱가포르·쿠웨이트·이스라엘은 수입시장 성장률과 유소년 비중이 낮아 기존 지표로는 낮게 평가됐습니다. 그러나 세
  나라 모두 외국 출신 인구 비중이 매우 높습니다. 특히 걸프 국가와 싱가포르에는 동남아·남아시아 출신 노동자층이 두텁습니다. 이들은 아시아식 간식에
  익숙하고, 이들을 상대하는 아시아계 식료품 유통망도 이미 갖춰져 있습니다. 그래서 한국 과자가 처음 진입하기 쉽고 수요가 빠르게 확산될 수 있습니다.
  이주민 인구가 늘면 식품 다양성 수요도 함께 늘기 때문에, 1인당 순이주 유입을 함께 넣어 변화 속도도 반영합니다. 이주민 비중은 소득(gdp_pc_ppp)과
  일부 겹치지만, 쿠웨이트처럼 소득 대비 비중이 유난히 높은 나라를 구분해 줄 수 있습니다. 이 지표는 앞서 기각된 '1인당 수입 수준'과 달리
  소비자 구성의 다양성을 측정합니다.
group: 소비트렌드
new_source_needed: ''
indicators:
- id: migrant_stock_share
  name_ko: 이주민 인구 비중
  group: 소비트렌드
  source: worldbank
  series: SM.POP.TOTL.ZS
  transform: level
  window: 1
  direction: 1
- id: net_migration_pc
  name_ko: 1인당 순이주 유입
  group: 소비트렌드
  source: worldbank
  series: SM.POP.NETM
  transform: per_capita
  window: 1
  direction: 1
proposed_by: llm:claude-opus-5-5
created: '2026-11-03'

### config/hypotheses/auto_auto_reexport_hub.yaml
id: auto_auto_reexport_hub
statement: 같은 품목을 다시 수출(재수출)하는 규모가 큰 유통·물류 허브 국가일수록, 자국 소비와 별개로 주변 시장으로 나가는 물량이 붙어
  이후 3년간 한국 과자 수출이 더 늘어난다.
rationale: 싱가포르(실제 7위, 모델 40위)와 쿠웨이트는 인구와 수입시장 성장률이 작아 저평가됐습니다. 그러나 두 나라는 각각 동남아와
  걸프·이라크 권역의 중계무역 거점입니다. 이런 나라로 가는 한국 수출은 자국 소비뿐 아니라 인근 국가로 재수출될 물량까지 포함하므로, 수입 규모나
  1인당 소비 지표로는 잡히지 않습니다. 해당국의 같은 품목 수출 규모, 그리고 인구로 나눈 1인당 수출 규모는 이 허브 기능을 직접 보여줍니다.
  특히 1인당 수출은 인구가 작은 허브를 큰 생산국과 구분해 줍니다. 한국 기업은 신규 권역에 진출할 때 허브국 유통사를 먼저 거치는 경우가 많습니다.
  따라서 허브 기능이 강한 나라일수록 이후 증가액이 크게 나타날 것으로 봅니다.
group: 수출입
new_source_needed: ''
indicators:
- id: partner_exports_size
  name_ko: 해당국 동일 품목 수출(재수출) 규모
  group: 수출입
  source: comtrade
  flow: X
  transform: level_log
  window: 1
  direction: 1
- id: partner_exports_pc
  name_ko: 해당국 1인당 동일 품목 수출
  group: 수출입
  source: comtrade
  flow: X
  transform: per_capita
  window: 1
  direction: 1
proposed_by: llm:claude-opus-5-5
created: '2026-11-03'

### config/hypotheses/auto_digital_adoption_speed.yaml
id: auto_digital_adoption_speed
statement: 인터넷 보급률이 빠르게 오르는 나라일수록 SNS를 통한 해외 간식 유행과 온라인 유통 확산이 일어나, 이후 3년간 한국 과자 수출이
  더 늘어난다.
rationale: 케냐·네팔·이라크처럼 모델이 하위권으로 본 저소득국에서도 실제 수출 증가가 상위권에 가까웠다. 이 나라들의 공통점은 같은 시기
  모바일 인터넷 이용자가 급증했다는 점이다. 한국 과자의 해외 수요는 유튜브·틱톡 먹방, 챌린지, 리뷰 콘텐츠로 퍼지는 경우가 많다. 인터넷 보급의
  '증가 속도'는 새로 온라인에 들어온 젊은 소비층의 크기를 나타낸다. 이는 한류 검색량(관심의 크기)이나 소득 수준과 다른 정보다. 콘텐츠에 노출될
  수 있는 인구 기반 자체가 늘어나는 정도를 보여주기 때문이다. 또 온라인 쇼핑과 소셜 커머스가 넓어지면 기존 수입 유통망이 약한 시장에서도 소량
  수입이 쉬워진다. 그래서 공식 수입시장이 작고 정체된 나라에서도 수출이 늘 신호를 미리 잡을 수 있다.
group: 소비트렌드
new_source_needed: ''
indicators:
- id: internet_users_change
  name_ko: 인터넷 이용률 상승 폭
  group: 소비트렌드
  source: worldbank
  series: IT.NET.USER.ZS
  transform: diff
  window: 3
  direction: 1
- id: broadband_change
  name_ko: 유선 초고속인터넷 가입 증가 폭
  group: 소비트렌드
  source: worldbank
  series: IT.NET.BBND.P2
  transform: diff
  window: 3
  direction: 1
proposed_by: llm:claude-opus-5-5
created: '2026-11-03'

### config/hypotheses/auto_food_import_dependence.yaml
id: auto_food_import_dependence
statement: 자국 식품 생산 기반이 약해 식품을 수입에 크게 의존하고, 1인당 수입 구매 수준이 높은 나라일수록 이후 3년간 한국 과자 수출이
  더 늘어난다.
rationale: 모델이 놓친 싱가포르·쿠웨이트·이스라엘·이라크는 모두 식품 소비의 상당 부분을 수입으로 채운다. 그러나 수입시장 성장률과 인구가
  낮게 잡혀 순위가 밀렸다. 현재 모델은 수입시장의 총규모(log)와 증가율만 보고, 국민 한 명이 수입 식품을 얼마나 사는지는 보지 않는다. 그래서
  인구는 작아도 수입품 소비가 생활화된 시장을 과소평가한다. 식품 수입 의존도가 높은 나라는 유통 채널이 이미 수입 브랜드에 열려 있다. 새 공급국
  제품이 진열대에 들어가는 비용이 낮아, 한국 과자처럼 신규 진입하는 제품의 물량이 빠르게 늘 수 있다. 1인당 수입액 '수준'은 시장 총규모나
  성장률과 구분되는 정보다. 수입 성장이 둔화된 고소득 소국에서도 이미 넓은 수입 소비층이 교체 수요로 신규 공급국을 받아들일 여지를 보여준다.
group: 수출입
new_source_needed: ''
indicators:
- id: food_import_share_merch
  name_ko: 상품수입 중 식품 비중
  group: 수출입
  source: worldbank
  series: TM.VAL.FOOD.ZS.UN
  transform: level
  window: 3
  direction: 1
- id: import_pc_level
  name_ko: 1인당 수입액 수준
  group: 수출입
  source: comtrade
  flow: M
  transform: per_capita
  window: 3
  direction: 1
proposed_by: llm:claude-opus-5-5
created: '2026-11-03'

### config/hypotheses/auto_korea_human_network.yaml
id: auto_korea_human_network
statement: 한국에 장기 체류하는 노동자·유학생과 현지 한인 동포 같은 인적 연결망이 두텁고, 해외 송금 유입이 큰 나라일수록 이후 3년간
  한국 과자 수출이 더 늘어난다.
rationale: 네팔은 고용허가제로 한국에 온 노동자가 매우 많은 나라다. 소득 수준과 수입시장 규모가 바닥인데도 실제 수출 증가 순위가 26위였다.
  아르헨티나는 남미 최대급 한인 사회가 있고, 케냐·이라크·쿠웨이트에는 한국 기업과 건설 인력의 현지 네트워크가 있다. 이미 채택된 방한 관광객
  지표는 단기 체류만 잡는다. 반면 장기 체류자는 귀국 뒤나 가족을 통해 한국 식품 소비 습관을 본국에 옮기고, 현지 한인 마트와 수입상 같은 유통
  거점을 만든다. 그래서 공식 수입 통계에 수요가 나타나기 전에 수출 증가를 먼저 보여줄 수 있다. 또 송금 유입은 GDP나 가계소비 통계에 다
  잡히지 않는 가계의 가처분 구매력이다. 특히 송금이 많은 저소득국에서는 포장 과자 같은 수입 간식 수요를 끌어올린다.
group: 소비트렌드
new_source_needed: '(1) moj_foreign_residents: 법무부 「출입국·외국인정책 통계연보」 국적별 체류외국인 수(연간,
  2005~). 공공데이터포털(data.go.kr) 또는 법무부 출입국·외국인정책본부 통계에서 국적별 연말 체류자 표를 받아 iso3,year,value
  CSV로 변환한다. (2) mofa_overseas_koreans: 외교부 「재외동포현황」 국가별 재외동포 수(격년 발간). 외교부 누리집 PDF
  또는 공공데이터포털 파일에서 받아 iso3,year,value CSV로 변환하고, 빠진 해는 직전 값으로 채운다.'
indicators:
- id: residents_in_korea_pc
  name_ko: 인구 대비 한국 체류자 수
  group: 소비트렌드
  source: external
  series: moj_foreign_residents
  transform: per_capita
  window: 3
  direction: 1
- id: overseas_koreans_pc
  name_ko: 인구 대비 현지 한인 동포 수
  group: 소비트렌드
  source: external
  series: mofa_overseas_koreans
  transform: per_capita
  window: 3
  direction: 1
- id: remittance_gdp
  name_ko: GDP 대비 개인 송금 유입
  group: 소비트렌드
  source: worldbank
  series: BX.TRF.PWKR.DT.GD.ZS
  transform: level
  window: 3
  direction: 1
proposed_by: llm:claude-opus-5-5
status: data_needed
reason: '미등록 외부 원천 moj_foreign_residents (new_source_needed: (1) moj_foreign_residents:
  법무부 「출입국·외국인정책 통계연보」 국적별 체류외국인 수(연간, 2005~). 공공데이터포털(data.go.kr) 또는 법무부 출입국·외국인정책본부
  통계에서 국적별 연말 체류자 표를 받아 iso3,year,value CSV로 변환한다. (2) mofa_overseas_koreans: 외교부
  「재외동포현황」 국가별 재외동포 수(격년 발간). 외교부 누리집 PDF 또는 공공데이터포털 파일에서 받아 iso3,year,value CSV로
  변환하고, 빠진 해는 직전 값으로 채운다.)'
created: '2026-11-03'

### config/criteria/k_export_agent.yaml
k_export.yaml의 12개 지표 블록을 그대로 쓰고(id, group, name_ko, source, series 또는 flow, transform, window, smooth, direction, weight 0.1, unit 모두 동일. 값이 '%'처럼 특수문자인 unit은 따옴표 처리), 다음이 달라집니다:
- 첫 줄 주석: # 에이전트가 생성한 기준(adopt). 원본 기준은 그대로 둔다.
- id: k_export_agent
- name_ko: K-푸드 수출 유망도 (3개 기준 통합, 카테고리 공통) · 에이전트 갱신
- universe는 블록 형식(min_population: 1000000, exclude_iso3: [KOR]을 '- KOR' 목록으로, min_indicator_coverage: 8, min_korea_exports_usd: 100000)
- benchmarks(momentum: korea_exports_cagr, size_only: korea_exports_size), min_window_n: 15, target(series: KOR_X, horizon: 3, kind: abs)
- indicators 끝에 두 개 추가:
- id: kfood_interest
  name_ko: 한국 음식 검색 관심도
  group: 소비트렌드
  source: external
  series: gtrends_kfood
  transform: level
  window: 3
  direction: 1
  unit: 0-100
  weight: 0.0
- id: korea_visitors_pc
  name_ko: 인구 대비 방한 관광객
  group: 소비트렌드
  source: external
  series: kto_visitors
  transform: per_capita
  window: 3
  direction: 1
  unit: 명/인
  weight: 0.0
(yaml.safe_dump로 키 순서를 유지해 기존 지표의 키 순서는 id, group, name_ko, source, … 입니다. 원문 371줄 전체가 필요하면 말씀해 주세요. 위 설명대로 k_export.yaml에서 기계적으로 재생성할 수 있습니다.)

(이어서 [4/4] 프롬프트 원문)


[4/4] prompt_round1.txt, prompt_round2.txt 원문과 k_export_agent.yaml 원문(3/4에서 요약했던 것을 손실 없이 다시 보냄)

### outputs/agent/dry_confectionery/prompt_round1.txt
현재 지표 12개:
[{"id": "import_market_size", "name_ko": "수입시장 규모", "group": "성장성", "source": "comtrade", "series": null, "flow": "M", "transform": "level_log"}, {"id": "import_market_cagr", "name_ko": "수입시장 성장률", "group": "성장성", "source": "comtrade", "series": null, "flow": "M", "transform": "cagr"}, {"id": "hh_consumption_pc_cagr", "name_ko": "1인당 실질 가계소비 성장률", "group": "성장성", "source": "worldbank", "series": "NE.CON.PRVT.PC.KD", "flow": null, "transform": "cagr"}, {"id": "population_size", "name_ko": "인구 규모", "group": "성장성", "source": "worldbank", "series": "SP.POP.TOTL", "flow": null, "transform": "level_log"}, {"id": "youth_share", "name_ko": "유소년(0-14세) 비중", "group": "소비트렌드", "source": "worldbank", "series": "SP.POP.0014.TO.ZS", "flow": null, "transform": "level"}, {"id": "urbanization_change", "name_ko": "도시화 진행 속도", "group": "소비트렌드", "source": "worldbank", "series": "SP.URB.TOTL.IN.ZS", "flow": null, "transform": "diff"}, {"id": "gdp_pc_ppp", "name_ko": "1인당 GDP(PPP)", "group": "소비트렌드", "source": "worldbank", "series": "NY.GDP.PCAP.PP.KD", "flow": null, "transform": "level_log"}, {"id": "import_pc_cagr", "name_ko": "1인당 수입 증가율", "group": "소비트렌드", "source": "comtrade", "series": null, "flow": "M", "transform": "per_capita_cagr"}, {"id": "korea_exports_size", "name_ko": "한국 수출 규모", "group": "수출입", "source": "comtrade", "series": null, "flow": "KOR_X", "transform": "level_log"}, {"id": "korea_exports_cagr", "name_ko": "한국 수출 성장률", "group": "수출입", "source": "comtrade", "series": null, "flow": "KOR_X", "transform": "cagr"}, {"id": "korea_share", "name_ko": "수입 중 한국산 비중", "group": "수출입", "source": "comtrade", "series": null, "flow": "KOR_X", "transform": "share"}, {"id": "korea_share_change", "name_ko": "한국산 비중 변화", "group": "수출입", "source": "comtrade", "series": null, "flow": "KOR_X", "transform": "share_diff"}]

지난 검증 기록(최근 20건):
[{"hypothesis": "kculture", "statement": "신흥국의 소득 성장과 별개로, 한류(K-문화) 확산이 큰 나라일수록 이후 3년간 한국 과자 수출이 더 늘었다.", "status": "accepted", "reason": "[채택] 표본 밖 7개 구간에서 순위상관이 평균 +0.059 변했고, 국가를 다시 뽑아 본 부트스트랩의 100%에서 기존 모델보다 나았다 (90% 구간 +0.025 ~ +0.096).\nkpop_interest: 소득·시장 규모를 통제한 편상관 평균 +0.04 (앞 시기 +0.10 → 최근 -0.02); 가중치 0.05 → 0.07.\nkpop_interest_change: 소득·시장 규모를 통제한 편상관 평균 -0.10 (앞 시기 -0.17 → 최근 -0.02); 가중치 0.02 → 0.06.\nkfood_interest: 소득·시장 규모를 통제한 편상관 평균 +0.19 (앞 시기 +0.21 → 최근 +0.16); 가중치 0.06 → 0.05.\nkorea_visitors_pc: 소득·시장 규모를 통제한 편상관 평균 +0.26 (앞 시기 +0.24 → 최근 +0.29); 가중치 0.15 → 0.03.\nlearn_korean_interest: 소득·시장 규모를 통제한 편상관 평균 +0.16 (앞 시기 +0.21 → 최근 +0.11); 가중치 0.12 → 0.06.\n  단독 투입 kpop_interest: weak (평균 +0.002, 우위 64%)\n  단독 투입 kpop_interest_change: rejected (평균 -0.001, 우위 39%)\n  단독 투입 kfood_interest: weak (평균 +0.008, 우위 85%)\n  단독 투입 korea_visitors_pc: accepted (평균 +0.054, 우위 99%)\n  단독 투입 learn_korean_interest: weak (평균 +0.006, 우위 72%)"}, {"hypothesis": "kculture", "statement": "신흥국의 소득 성장과 별개로, 한류(K-문화) 확산이 큰 나라일수록 이후 3년간 한국 과자 수출이 더 늘었다.", "status": "accepted", "reason": "[채택] 표본 밖 7개 구간에서 순위상관이 평균 +0.029 변했고, 국가를 다시 뽑아 본 부트스트랩의 90%에서 기존 모델보다 나았다 (90% 구간 -0.007 ~ +0.062).\nkpop_interest: 소득·시장 규모를 통제한 편상관 평균 +0.08 (앞 시기 +0.18 → 최근 -0.02); 가중치 0.08 → 0.08.\nkpop_interest_change: 소득·시장 규모를 통제한 편상관 평균 -0.12 (앞 시기 -0.22 → 최근 -0.02); 가중치 0.01 → 0.05.\nkfood_interest: 소득·시장 규모를 통제한 편상관 평균 +0.26 (앞 시기 +0.31 → 최근 +0.21); 가중치 0.09 → 0.07.\nkorea_visitors_pc: 소득·시장 규모를 통제한 편상관 평균 +0.10 (앞 시기 +0.13 → 최근 +0.07); 가중치 0.15 → 0.03.\nlearn_korean_interest: 소득·시장 규모를 통제한 편상관 평균 +0.20 (앞 시기 +0.27 → 최근 +0.13); 가중치 0.12 → 0.04.\n  단독 투입 kpop_interest: rejected (평균 -0.009, 우위 9%)\n  단독 투입 kpop_interest_change: rejected (평균 -0.002, 우위 44%)\n  단독 투입 kfood_interest: weak (평균 +0.018, 우위 91%)\n  단독 투입 korea_visitors_pc: weak (평균 +0.019, 우위 93%)\n  단독 투입 learn_korean_interest: rejected (평균 -0.002, 우위 42%)"}]

최근 창에서 모델이 놓친 나라(실제 순위 vs 모델 순위, 지표 백분위):
[{"iso3": "SGP", "name": "Singapore", "actual_rank": 7, "model_rank": 40, "n": 57, "indicators_pct": {"import_market_size": 56.0, "import_market_cagr": 9.0, "hh_consumption_pc_cagr": 55.0, "population_size": 19.0, "youth_share": 5.0, "urbanization_change": 20.0, "gdp_pc_ppp": 100.0, "import_pc_cagr": 18.0, "korea_exports_size": 82.0, "korea_exports_cagr": 26.0, "korea_share": 81.0, "korea_share_change": 39.0}}, {"iso3": "KWT", "name": "Kuwait", "actual_rank": 21, "model_rank": 51, "n": 57, "indicators_pct": {"import_market_size": 42.0, "import_market_cagr": 14.0, "hh_consumption_pc_cagr": 7.0, "population_size": 11.0, "youth_share": 58.0, "urbanization_change": 20.0, "gdp_pc_ppp": 67.0, "import_pc_cagr": 11.0, "korea_exports_size": 63.0, "korea_exports_cagr": 28.0, "korea_share": 67.0, "korea_share_change": 32.0}}, {"iso3": "ARG", "name": "Argentina", "actual_rank": 28, "model_rank": 52, "n": 57, "indicators_pct": {"import_market_size": 11.0, "import_market_cagr": 11.0, "hh_consumption_pc_cagr": 4.0, "population_size": 67.0, "youth_share": 61.0, "urbanization_change": 42.0, "gdp_pc_ppp": 39.0, "import_pc_cagr": 16.0, "korea_exports_size": 30.0, "korea_exports_cagr": 7.0, "korea_share": 54.0, "korea_share_change": 19.0}}, {"iso3": "NPL", "name": "Nepal", "actual_rank": 26, "model_rank": 49, "n": 57, "indicators_pct": {"import_market_size": 7.0, "import_market_cagr": 39.0, "hh_consumption_pc_cagr": 93.0, "population_size": 51.0, "youth_share": 84.0, "urbanization_change": 53.0, "gdp_pc_ppp": 2.0, "import_pc_cagr": 40.0, "korea_exports_size": 23.0, "korea_exports_cagr": 23.0, "korea_share": 56.0, "korea_share_change": 25.0}}, {"iso3": "ITA", "name": "Italy", "actual_rank": 22, "model_rank": 44, "n": 57, "indicators_pct": {"import_market_size": 86.0, "import_market_cagr": 21.0, "hh_consumption_pc_cagr": 24.0, "population_size": 74.0, "youth_share": 7.0, "urbanization_change": 14.0, "gdp_pc_ppp": 65.0, "import_pc_cagr": 44.0, "korea_exports_size": 35.0, "korea_exports_cagr": 88.0, "korea_share": 12.0, "korea_share_change": 60.0}}, {"iso3": "KEN", "name": "Kenya", "actual_rank": 38, "model_rank": 55, "n": 57, "indicators_pct": {"import_market_size": 2.0, "import_market_cagr": 63.0, "hh_consumption_pc_cagr": 65.0, "population_size": 70.0, "youth_share": 100.0, "urbanization_change": 9.0, "gdp_pc_ppp": 5.0, "import_pc_cagr": 51.0, "korea_exports_size": 4.0, "korea_exports_cagr": 37.0, "korea_share": 58.0, "korea_share_change": 40.0}}, {"iso3": "IRQ", "name": "Iraq", "actual_rank": 42, "model_rank": 57, "n": 57, "indicators_pct": {"import_market_size": 5.0, "import_market_cagr": 18.0, "hh_consumption_pc_cagr": 5.0, "population_size": 63.0, "youth_share": 98.0, "urbanization_change": 16.0, "gdp_pc_ppp": 21.0, "import_pc_cagr": 7.0, "korea_exports_size": 2.0, "korea_exports_cagr": 2.0, "korea_share": 44.0, "korea_share_change": 12.0}}, {"iso3": "ISR", "name": "Israel", "actual_rank": 33, "model_rank": 46, "n": 57, "indicators_pct": {"import_market_size": 54.0, "import_market_cagr": 88.0, "hh_consumption_pc_cagr": 51.0, "population_size": 30.0, "youth_share": 81.0, "urbanization_change": 12.0, "gdp_pc_ppp": 60.0, "import_pc_cagr": 82.0, "korea_exports_size": 16.0, "korea_exports_cagr": 93.0, "korea_share": 19.0, "korea_share_change": 65.0}}]

외부 데이터 목록:
[{"series": "gtrends_kpop", "desc": "구글 트렌드 K-pop 검색 관심도(국가별, 연간)", "kind": "gtrends", "ready": true, "how": ""}, {"series": "gtrends_kdrama", "desc": "구글 트렌드 한국 드라마 검색 관심도", "kind": "gtrends", "ready": true, "how": ""}, {"series": "gtrends_kfood", "desc": "구글 트렌드 한국 음식 검색 관심도", "kind": "gtrends", "ready": true, "how": ""}, {"series": "gtrends_learnkorean", "desc": "구글 트렌드 한국어 학습 검색 관심도(한류 동호회 통계의 대체: 국가별 연간 자료가 PDF로만 있어 자동화 불가)", "kind": "gtrends", "ready": true, "how": ""}, {"series": "kto_visitors", "desc": "국적별 방한 외래관광객 수(한국관광공사 관광지식정보시스템 입국관광통계, 2005~)", "kind": "kto", "ready": true, "how": "know.tour.go.kr/stat/entryTourStatDis19Re.do 국적별·연간 조회를 fetch_kto_visitors 가 자동 수집"}, {"series": "kf_hallyu_members", "desc": "국가별 한류 동호회 회원 수(외교부·한국국제교류재단 「지구촌 한류현황」 책자, 비정기 PDF) — 선택", "kind": "file", "ready": false, "how": "책자 PDF의 국가별 표 → iso3,year,value CSV (자동화 대상 아님)"}]

다음에 시험할 가설을 최대 3개 내라.

### outputs/agent/dry_confectionery/prompt_round2.txt
round1과 다른 부분은 '지난 검증 기록' 배열뿐입니다. 나머지 블록(현재 지표 12개, 모델이 놓친 나라 8개, 외부 데이터 목록, 마지막 줄)은 round1과 글자 하나까지 같습니다(같은 패널·같은 t=2021·같은 seed라 놓친 나라도 동일).
'지난 검증 기록' 배열 = round1 배열의 kculture 2건 그대로 + 아래 3건이 순서대로 이어짐:
{"hypothesis": "auto_korea_human_network", "statement": "한국에 장기 체류하는 노동자·유학생과 현지 한인 동포 같은 인적 연결망이 두텁고, 해외 송금 유입이 큰 나라일수록 이후 3년간 한국 과자 수출이 더 늘어난다.", "status": "data_needed", "reason": "미등록 외부 원천 moj_foreign_residents (new_source_needed: (1) moj_foreign_residents: 법무부 「출입국·외국인정책 통계연보」 국적별 체류외국인 수(연간, 2005~). 공공데이터포털(data.go.kr) 또는 법무부 출입국·외국인정책본부 통계에서 국적별 연말 체류자 표를 받아 iso3,year,value CSV로 변환한다. (2) mofa_overseas_koreans: 외교부 「재외동포현황」 국가별 재외동포 수(격년 발간). 외교부 누리집 PDF 또는 공공데이터포털 파일에서 받아 iso3,year,value CSV로 변환하고, 빠진 해는 직전 값으로 채운다.)"}, {"hypothesis": "auto_food_import_dependence", "statement": "자국 식품 생산 기반이 약해 식품을 수입에 크게 의존하고, 1인당 수입 구매 수준이 높은 나라일수록 이후 3년간 한국 과자 수출이 더 늘어난다.", "status": "rejected", "reason": "[기각] 표본 밖 7개 구간에서 순위상관이 평균 -0.032 변했고, 국가를 다시 뽑아 본 부트스트랩의 1%에서 기존 모델보다 나았다 (90% 구간 -0.057 ~ -0.008).\nfood_import_share_merch: 소득·시장 규모를 통제한 편상관 평균 -0.10 (앞 시기 -0.05 → 최근 -0.15); 가중치 0.02 → 0.02.\nimport_pc_level: 소득·시장 규모를 통제한 편상관 평균 -0.03 (앞 시기 -0.00 → 최근 -0.06); 가중치 0.07 → 0.05.\n  주의: gdp_pc_ppp와 순위상관 0.82로 정보가 겹침.\n  단독 투입 food_import_share_merch: rejected (평균 -0.022, 우위 2%)\n  단독 투입 import_pc_level: rejected (평균 -0.004, 우위 35%)"}, {"hypothesis": "auto_digital_adoption_speed", "statement": "인터넷 보급률이 빠르게 오르는 나라일수록 SNS를 통한 해외 간식 유행과 온라인 유통 확산이 일어나, 이후 3년간 한국 과자 수출이 더 늘어난다.", "status": "rejected", "reason": "[기각] 표본 밖 7개 구간에서 순위상관이 평균 -0.016 변했고, 국가를 다시 뽑아 본 부트스트랩의 15%에서 기존 모델보다 나았다 (90% 구간 -0.044 ~ +0.009).\ninternet_users_change: 소득·시장 규모를 통제한 편상관 평균 -0.08 (앞 시기 -0.30 → 최근 +0.14); 가중치 0.02 → 0.08.\nbroadband_change: 소득·시장 규모를 통제한 편상관 평균 -0.07 (앞 시기 -0.05 → 최근 -0.08); 가중치 0.03 → 0.03.\n  단독 투입 internet_users_change: weak (평균 +0.012, 우위 92%)\n  단독 투입 broadband_change: rejected (평균 -0.022, 우위 8%)"}
(round2 파일은 round1 텍스트에서 '지난 검증 기록' 배열만 위 5건짜리로 바꾸면 바이트 단위로 같습니다. 12,625바이트)

### config/criteria/k_export_agent.yaml (원문)
# 에이전트가 생성한 기준(adopt). 원본 기준은 그대로 둔다.
id: k_export_agent
name_ko: K-푸드 수출 유망도 (3개 기준 통합, 카테고리 공통) · 에이전트 갱신
universe:
  min_population: 1000000
  exclude_iso3:
  - KOR
  min_indicator_coverage: 8
  min_korea_exports_usd: 100000
benchmarks:
  momentum: korea_exports_cagr
  size_only: korea_exports_size
min_window_n: 15
target:
  series: KOR_X
  horizon: 3
  kind: abs
indicators:
- id: import_market_size
  group: 성장성
  name_ko: 수입시장 규모
  source: comtrade
  flow: M
  transform: level_log
  window: 3
  direction: 1
  weight: 0.1
  unit: ln(USD)
- id: import_market_cagr
  group: 성장성
  name_ko: 수입시장 성장률
  source: comtrade
  flow: M
  transform: cagr
  window: 5
  smooth: 3
  direction: 1
  weight: 0.1
  unit: '%/년'
- id: hh_consumption_pc_cagr
  group: 성장성
  name_ko: 1인당 실질 가계소비 성장률
  source: worldbank
  series: NE.CON.PRVT.PC.KD
  transform: cagr
  window: 5
  smooth: 3
  direction: 1
  weight: 0.1
  unit: '%/년'
- id: population_size
  group: 성장성
  name_ko: 인구 규모
  source: worldbank
  series: SP.POP.TOTL
  transform: level_log
  window: 1
  direction: 1
  weight: 0.1
  unit: ln(명)
- id: youth_share
  group: 소비트렌드
  name_ko: 유소년(0-14세) 비중
  source: worldbank
  series: SP.POP.0014.TO.ZS
  transform: level
  window: 1
  direction: 1
  weight: 0.1
  unit: '%'
- id: urbanization_change
  group: 소비트렌드
  name_ko: 도시화 진행 속도
  source: worldbank
  series: SP.URB.TOTL.IN.ZS
  transform: diff
  window: 5
  direction: 1
  weight: 0.1
  unit: '%p/5년'
- id: gdp_pc_ppp
  group: 소비트렌드
  name_ko: 1인당 GDP(PPP)
  source: worldbank
  series: NY.GDP.PCAP.PP.KD
  transform: level_log
  window: 1
  direction: 1
  weight: 0.1
  unit: ln(USD)
- id: import_pc_cagr
  group: 소비트렌드
  name_ko: 1인당 수입 증가율
  source: comtrade
  flow: M
  transform: per_capita_cagr
  window: 5
  smooth: 3
  direction: 1
  weight: 0.1
  unit: '%/년'
- id: korea_exports_size
  group: 수출입
  name_ko: 한국 수출 규모
  source: comtrade
  flow: KOR_X
  transform: level_log
  window: 3
  direction: 1
  weight: 0.1
  unit: ln(USD)
- id: korea_exports_cagr
  group: 수출입
  name_ko: 한국 수출 성장률
  source: comtrade
  flow: KOR_X
  transform: cagr
  window: 5
  smooth: 3
  direction: 1
  weight: 0.1
  unit: '%/년'
- id: korea_share
  group: 수출입
  name_ko: 수입 중 한국산 비중
  source: comtrade
  flow: KOR_X
  transform: share
  window: 3
  direction: 1
  weight: 0.1
  unit: '%'
- id: korea_share_change
  group: 수출입
  name_ko: 한국산 비중 변화
  source: comtrade
  flow: KOR_X
  transform: share_diff
  window: 5
  direction: 1
  weight: 0.1
  unit: '%p/5년'
- id: kfood_interest
  name_ko: 한국 음식 검색 관심도
  group: 소비트렌드
  source: external
  series: gtrends_kfood
  transform: level
  window: 3
  direction: 1
  unit: 0-100
  weight: 0.0
- id: korea_visitors_pc
  name_ko: 인구 대비 방한 관광객
  group: 소비트렌드
  source: external
  series: kto_visitors
  transform: per_capita
  window: 3
  direction: 1
  unit: 명/인
  weight: 0.0

보고 끝. 요약: LLM이 낸 6개 가설은 데이터 필요 1, 기각 4, 보류 1이고, 한류 가설은 방한객 지표(KTO)만 실데이터로 유효합니다. 구글 트렌드 수집은 0/100 문제를 고쳐야 다시 판정할 수 있습니다.
