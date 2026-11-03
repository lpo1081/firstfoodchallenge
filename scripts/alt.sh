#!/bin/sh
# 다른 방법 3가지(제2의 베트남 찾기·수출 갭·일본 과자 추적)로 진출국 찾기 + 기존 3대 기준 결과와 합의표.
# 기존 모델·결과는 읽기만 하고 고치지 않는다. 결과: outputs/alt_methods/report.md, result.json
# 새로 받는 데이터(처음 한 번): 일본 상대국별 과자 수출(Comtrade), 나라 중심 좌표(GitHub 공개 파일). API 비용 0원.
cd "$(dirname "$0")/.." || exit 1
.venv/bin/python -m kfood_scout.alt "$@"
