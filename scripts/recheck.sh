#!/bin/sh
# 외부 검토(2026-11-03) 반영 재검증. API 비용 0원(저장된 데이터만, --no-fetch).
# 1) 2021→24 구간을 봉인한 채 가설을 다시 검증 → 2) 채택 지표로 기준 재생성 → 3) 봉인 구간 성적
# 4) 적중률(미국·중국 제외, 증가율 기준, 큰 시장 순 대조군) → 5) 새 TOP3 와 TOP3 확률
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
for h in config/hypotheses/*.yaml; do
  id=$(basename "$h" .yaml)
  echo "=== test $id $(date)"; $PY -m kfood_scout.agent test --hyp "$id" --no-fetch
done
echo "=== adopt $(date)";  $PY -m kfood_scout.agent adopt --no-fetch
echo "=== sealed abs $(date)"; $PY -m kfood_scout.agent sealed --no-fetch
echo "=== sealed log $(date)"; $PY -m kfood_scout.agent sealed --no-fetch --target-kind log
echo "=== hit_rate $(date)"; $PY scripts/hit_rate.py
echo "=== study $(date)"; $PY -m kfood_scout study --study agent_vs_base --no-fetch
echo "=== END $(date)"
