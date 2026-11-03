# kfood_scout — K-푸드 수출 유망국 발굴 에이전트 파이프라인

기준(criterion) × 카테고리(category) 조합마다 같은 코드를 반복 실행해 유망국을 뽑고,
실제 진출 이력으로 역산 검증한다. 1차 범위: **식품시장 성장성 × 건식 과자류(빙과 제외)**.

## 실행
```bash
pip install -r requirements.txt
python -m kfood_scout all --as-of 2023          # 수집 → 스코어 → 역산 검증 → 대시보드
python -m kfood_scout score --as-of 2023 --weights import_market_cagr=0.5,population_size=0.05
python -m kfood_scout validate                   # 패널이 있으면 오프라인 반복 실행
pytest -q tests                                  # 합성 데이터로 로직 검증
```
- UN Comtrade 무료 키가 있으면 `export COMTRADE_API_KEY=...` (없으면 public preview 사용, 더 느림)
- 필요한 접속 도메인: `comtradeapi.un.org`, `api.worldbank.org`

## 구조
| 경로 | 역할 |
|---|---|
| `config/categories.yaml` | 카테고리 = HS 6단위 코드 묶음. 새 식품군은 블록 추가만 하면 됨 |
| `config/criteria/market_growth.yaml` | 기준 1의 지표 5개(원천·변환·방향·가중치·의미) + 검증용 후보 지표 |
| `config/entries/lotte_wellfood.yaml` | 롯데웰푸드 해외 진출 8건(연도·방식·출처) = 역산 정답 세트 |
| `kfood_scout/sources/` | 원천별 수집기(World Bank, UN Comtrade) + 디스크 캐시 |
| `kfood_scout/indicators.py` | 기준연도(as_of) 시점 지표 계산. 미래 데이터 차단 |
| `kfood_scout/scoring.py` | 평가대상국 필터 → 백분위 정규화 → 가중합 |
| `kfood_scout/validation.py` | 시점 재현 · 가중치 전수 역산(10,626 조합) · 신규 지표 후보 검토 |
| `kfood_scout/report.py`, `dashboard_template.html` | 마크다운 리포트, CSV, 가중치 슬라이더 대시보드 |
| `outputs/<category>__<criterion>/` | 결과물 |

## 비교 설계(study): 가로·세로 비교군을 설정만으로 추가/삭제
```bash
python -m kfood_scout plan    --study lotte_top5   # 남은 Comtrade 호출 수(쿼터 계획)
python -m kfood_scout study   --study lotte_top5   # 부족분만 수집 → 조합별 롤링 역산 → 비교
python -m kfood_scout compare --study lotte_top5   # 저장 결과로 비교만 다시
```
| 층 | 파일 | 추가/삭제 방법 |
|---|---|---|
| 원천 저장소 | `kfood_scout/store.py` → `data/store/` | HS 코드 1개 × 흐름 1개 = 파일 1개. 카테고리가 바뀌어도 받은 코드는 재수집 안 함. 새 흐름(예: 일본 수출)은 `FETCHERS` 에 함수 1개 |
| 카테고리 | `config/categories.yaml` | HS 코드 블록 추가 |
| 기준·지표 | `config/criteria/*.yaml` | 지표 줄 추가/삭제, 그룹 이름 자유 |
| 기업 포트폴리오 | `config/portfolios/*.yaml` | 카테고리별 매출 비중 → 통합 순위 가중치 |
| 비교 설계 | `config/studies/*.yaml` | `axes`(category·criterion·method·target…)에 값 추가/삭제, `baseline`=대조군, `overrides`=특정 조합만 설정 변경 |
| 방법 | `study.METHODS` | 분석 함수 1개 등록 |
| 새 축 | `study.apply_axis` | 분기 1개 추가 |
| 비교 지표 | `compare.METRICS`, `compare.SIMILARITY` | 함수 1개 추가 |

같은 설정·같은 데이터의 조합은 이전 결과를 재사용하므로, 축에 값을 하나 더해도 그 조합만 새로 계산된다.

## 확장 방법
- 다른 식품군: `categories.yaml` 에 HS 코드 블록 추가 → `--category <id>`
- 다른 기준(소비 트렌드, 수출입 현황): `config/criteria/<id>.yaml` 추가 → `--criterion <id>`
- 다른 기업 검증: `config/entries/<company>.yaml` 추가 → `--entries <company>`

## 에이전트 루프: 가설 → 지표화 → 백테스트 → 채택/기각 → 근거 기록
```bash
pip install pytrends anthropic                                   # 구글 트렌드 수집, LLM 가설 제안
python -m kfood_scout.agent list                                 # 가설 목록, 외부 데이터 준비 상태
python -m kfood_scout.agent test --hyp kculture                  # 가설 하나 검증(데이터 없으면 수집)
python -m kfood_scout.agent test --hyp kculture --target-kind log  # 정답을 증가율로 바꿔 재검증
python -m kfood_scout.agent loop --rounds 2 --n 3                # LLM이 못 맞힌 나라를 보고 가설 제안 → 검증 반복
python -m kfood_scout.agent adopt                                # 채택 지표 합치고 가중치≈0 지표 제거 → criteria/k_export_agent.yaml
python -m kfood_scout.agent report                               # outputs/agent/<category>/report.md
```
| 층 | 파일 | 추가/삭제 방법 |
|---|---|---|
| 외부 원천 | `kfood_scout/sources/external.py` | `SOURCES` 에 이름 1개 등록(구글 트렌드 키워드, 또는 `data/external/raw/*.csv` 파일). 지표에서 `source: external, series: <이름>` |
| 가설 | `config/hypotheses/*.yaml` | 파일 1개 = 가설 1개(문장·근거·지표). LLM 제안분은 `auto_*.yaml` |
| 검증 | `kfood_scout/agent/evaluate.py` | 1년 간격 창, 겹치지 않는 표본 밖 구간(t→t+3), 부트스트랩 우위 확률, 소득 통제 편상관, 기존 지표와 중복. 판정 기준 `DEFAULT_RULES` |
| 기록 | `outputs/agent/<category>/ledger.jsonl` | 모든 판정과 근거가 쌓이고 다음 가설 제안의 입력이 됨 |

### 자율 실행과 데이터 탐색 (2026-11-03)
- `python -m kfood_scout.agent auto --budget 1.0` : 가설 제안 → (데이터 없으면) 데이터 탐색 → 검증 → 기록을 반복. 채택이 `--patience`(기본 2) 라운드 연속 없거나 예산에 닿으면 스스로 종료하고, 채택분이 있으면 adopt·report 까지.
- `agent/scout.py` : Claude 가 web_search/web_fetch 로 원천을 찾고 '수집 명세'(주소·형식·열 이름)를 만든다. 내려받기·해석은 고정 코드(load_spec)가 하고, 국가 30개·연도 8개·연도별 고유값 5개 검사를 통과해야 `config/sources/auto_sources.yaml` 에 등록된다. Claude 가 쓴 코드는 실행하지 않는다.
- `agent/cost.py` : 모든 API 호출의 비용을 `outputs/agent/costs.jsonl` 에 기록. `python -m kfood_scout.agent cost` 로 합계.
- 값 퇴화 검사: 후보 지표의 고유값이 5개 미만이면 검증에서 빼고 '퇴화'로 표시(구글 트렌드 0/100 사고 재발 방지). 구글 트렌드는 키워드별로 따로 요청하도록 수정. 맥북의 `data/store/external/gtrends_*.csv` 는 지우고 다시 받아야 함.
