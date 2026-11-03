#!/bin/sh
# 진출 비용 반영 우선순위 (API 호출 없음, 비용 0원). 결과: outputs/entry_cost/report.md
cd "$(dirname "$0")/.." && .venv/bin/python -m kfood_scout.entry_cost "$@"
