#!/bin/sh
# 에이전트 2차 실행 (형님 승인, LLM 비용 상한 1달러)
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
echo "=== test abs $(date)"; $PY -m kfood_scout.agent test --hyp kculture
echo "=== test log $(date)"; $PY -m kfood_scout.agent test --hyp kculture --target-kind log
echo "=== auto $(date)"; $PY -m kfood_scout.agent auto --budget 1.0
echo "=== cost $(date)"; $PY -m kfood_scout.agent cost
echo "=== report $(date)"; $PY -m kfood_scout.agent report
echo "=== END $(date)"
