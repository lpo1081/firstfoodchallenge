#!/bin/sh
# 통합 진출국 선정 깔때기(대기업 표준 5단계). API 비용 0원.
# 처음 한 번 공개 미러(세계은행 물가·환율·물류지수·GDP 성장률, 국가 좌표)를 받아 data/store 에 저장하고, 이후엔 저장분만 쓴다.
# 결과: outputs/funnel/biscuits/report.md (사람용), result.json
cd "$(dirname "$0")/.." || exit 1
.venv/bin/python -m kfood_scout.funnel "$@"
# 결과 화면(HTML 한 장): outputs/funnel/biscuits/screen.html — 화면 생성기(PR #15)가 머지돼 있을 때만
if [ -f kfood_scout/screen_funnel.py ]; then
  .venv/bin/python -m kfood_scout.screen_funnel --category biscuits
fi
