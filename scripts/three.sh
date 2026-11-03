#!/bin/sh
# 3대 기준(성장성·트렌드·수출입) TOP3 확정. API 비용 0원.
# 새로 받는 것: 세계은행 거버넌스 지표 3개(정치 안정·법치·부패, 무료). 무역 데이터는 저장분만 사용(Comtrade 호출 없음).
# 결과: outputs/three_criteria/report.md (사람용), result.json, ranking.json(레드팀 critic 입력)
cd "$(dirname "$0")/.." || exit 1
.venv/bin/python -m kfood_scout.three "$@"
