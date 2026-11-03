#!/bin/sh
# 에이전트 실행 순서 (형님 승인 작업). 실패해도 다음 단계로 진행하고 로그에 남긴다.
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
echo "=== test abs $(date)"; $PY -m kfood_scout.agent test --hyp kculture --category dry_confectionery
echo "=== test log $(date)"; $PY -m kfood_scout.agent test --hyp kculture --category dry_confectionery --target-kind log
echo "=== loop $(date)"; $PY -m kfood_scout.agent loop --rounds 2 --n 3
echo "=== adopt $(date)"; $PY -m kfood_scout.agent adopt
echo "=== report $(date)"; $PY -m kfood_scout.agent report
echo "=== END $(date)"
