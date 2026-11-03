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

### 레드팀(비판 에이전트)과 가설 장부 (2026-11-03)
- `python -m kfood_scout.agent critic --budget 1.0` : 후보국마다 Claude 가 최근 2년 기사·규제·정치 뉴스를 검색(국가당 4회 상한)해 "이 나라를 뽑으면 안 되는 이유"를 반론 카드로 낸다. 후보는 `config/critic.yaml`, 또는 3대 기준 순위 `--ranking outputs/three_criteria/ranking.json --top 5`, `--ranking 순위파일(csv/json, iso3)` `--countries PHL,IDN` `--top 6`.
- 판정은 고정 코드(`agent/critic.py` `judge`)가 한다: 실제 검색 결과에 나온 주소만 근거로 인정(지어낸 출처 차단), 2년보다 오래된 기사 제외, '치명'은 서로 다른 출처 2곳 이상일 때만, 치명 1개면 **배제 권고**·중간 2개면 **주의**·그 외 **유지**. 규칙은 `config/critic.yaml` `rules`.
- 숫자로 측정 가능한 반론은 `outputs/agent/critic/seeds.json`(가설 씨앗)에 쌓이고, 다음 `agent auto/loop` 때 가설 담당 AI 프롬프트에 들어가 지표 가설(critic_)로 바뀌어 통계 검증을 받는다. 기사(비정형) → 가설 → 숫자(정형) 판정.
- 본 나라는 30일 동안 캐시 재사용(무료). 예산이 모자라 못 본 나라는 같은 명령을 다시 치면 이어서 본다.
- `python -m kfood_scout.agent board` : 가설 장부 `outputs/agent/<category>/board.md` — 가설(누가 냈나)·표본 밖 검증·레드팀 판정·근거 링크·버린 반론·다음 가설 후보를 한 장에(비용 0).

### 외부 검토 반영 (2026-11-03): 성적 과대평가 방지
- **봉인 구간**: 2021→24 정답은 가설 선택·adopt 에서 보지 않는다(`agent/loop.py` `SEAL_FROM`, 선택용 창 2012~2018). 성적은 `python -m kfood_scout.agent sealed` 로만 확인. 옛(봉인 전) 검증 결과는 adopt 에서 자동 제외되고, 새 기준 파일에 `selection.last_start` 가 기록된다.
- **적중률 재계산** `scripts/hit_rate.py`: 정답 abs/log × 국가 전체/미국·중국 제외, 대조군에 '큰 시장 순(한국 수출 규모 순)' 추가, 요약은 전체 7구간·안 겹치는 3구간·봉인 1구간으로 나눔. '무작위 대비 ○배'만으로 발표하지 말 것(미국이 매 구간 1위라 적중 수가 부풀려짐).
- **XX**: 기본을 추세 연장 → 최신 X(`combine: latest`)로 변경. 세 방식(latest·mean2·extrapolate)의 성적은 `xx_test` 에 함께 남음.
- **TOP-k 확률**: 마지막 구간 국가를 다시 뽑아 가중치를 `top_prob_B`(기본 200)번 다시 찾고, 각 나라가 TOP3·5·10 에 든 비율을 `forecast_XX[].prob` 에 기록.
- **정답 기본값 = 증가액(abs)**(증가율은 실데이터에서 TOP3 적중 0이라 보조로만), **체급별 비교**(`tiers: 3`): 한국 수출 규모 3분위(큰·중간·작은 시장)로 나눠 `forecast_XX[].tier`·`tier_rank`, hit_rate 의 `tier:*` 시나리오로 체급 안 순위·적중률을 본다. 모델은 하나(표본 54개국 유지), 비교·발표만 체급별.
- 맥북 한 번에 실행: `sh scripts/recheck.sh` (비용 0원).

### 두 축: 수출 유망도 × 현지 시장 성장성 (2026-11-03)
- 축 1 `k_export_agent`: 한국 과자 **수출** 증가를 맞히는 모델(수출로 공략할 나라).
- 축 2 `config/criteria/local_market.yaml`: 그 나라 과자류 **실소비**(UNIDO IDSB: 현지 생산+수입−수출, ISIC 1071·1073) 증가를 맞히는 모델. 1차(전체 수입 증가)는 '큰 시장 순'보다 못하고 인도를 놓쳐 교체. 수집: `scripts/fetch_unido.py`(무료 API, `sources/external.py` kind=unido).
- `scripts/two_axis.py`: 둘 다 상위 1/3 = 수출 우선, 축 2만 = 현지생산·인수 검토, 축 1만 = 수출 유지·확대. 나라마다 각 축 점수를 올린 지표 3개를 이유로 표시 → `outputs/two_axis/two_axis.md`.
- 한계: UNIDO 4자리 자료는 2023년까지, 일부 개발도상국은 보고가 비어 있을 수 있음.
- 실행: `sh scripts/recheck.sh` 에 포함(비용 0).
