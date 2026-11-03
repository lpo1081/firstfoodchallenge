"""적중률: 과거 각 시점에 모델이 뽑은 TOP-k 중 몇 개가 실제로 3년 뒤 '수출 증가 TOP-k'에 들었나.

비교 대상
- 모델: t년에 역산한 가중치(X)로 t+3년 시점 국가 순위를 매김(정답 기간이 겹치지 않는 표본 밖 예측)
- 단순 추세: '지난 3년간 수출이 많이 늘어난 나라가 계속 는다'(직전 3년 증가액 순)
- 무작위: k개를 아무렇게나 뽑았을 때 기대 적중 수 = k × k / 국가 수

실행(API 비용 없음, 저장된 데이터만 사용):
  .venv/bin/python scripts/hit_rate.py            # k_export, k_export_agent 둘 다
결과: outputs/hit_rate/hit_rate.json 과 화면 요약
"""
import json
import sys

import pandas as pd

from kfood_scout import store
from kfood_scout.agent import evaluate as ev
from kfood_scout.agent import loop
from kfood_scout.config import ROOT, criterion_from_dict, load_criterion_raw

CAT = "dry_confectionery"
KS = (3, 5, 10)
H = 3


def run(crit_id: str, countries) -> list[dict]:
    raw = load_criterion_raw(crit_id)
    crit = criterion_from_dict(raw)
    panel = loop.panel_for(CAT, raw, fetch=False, log=lambda *a: None)
    wins = ev._windows(panel, countries, crit, CAT, range(2012, 2022), 8000, 0)
    ev._fit_all(wins, 8000, 0)
    name = countries.set_index("iso3")["name"].to_dict()
    rows = []
    for t in sorted(wins):
        s = t + H
        if s not in wins:
            continue
        P, y = wins[s]["pct"], wins[s]["y"]
        score = pd.Series(P.to_numpy() @ wins[t]["w"], index=P.index)
        prev = wins[t]["y"].reindex(P.index)  # 직전 3년(t→s) 증가액 = 단순 추세 예측
        n = len(y)
        rec = {"fit": t, "test": f"{s}->{s + H}", "n": n}
        for k in KS:
            act = set(y.nlargest(k).index)
            rec[f"model_hit{k}"] = len(set(score.nlargest(k).index) & act)
            rec[f"trend_hit{k}"] = len(set(prev.dropna().nlargest(k).index) & act)
            rec[f"random_hit{k}"] = round(k * k / n, 2)
        rec["model_top3"] = [name.get(c, c) for c in score.nlargest(3).index]
        rec["actual_top3"] = [name.get(c, c) for c in y.nlargest(3).index]
        # 모델 TOP3 가 실제로는 몇 등이었나(국가 수 중)
        ar = y.rank(ascending=False)
        rec["model_top3_actual_rank"] = [int(ar[c]) for c in score.nlargest(3).index]
        rows.append(rec)
    return rows


def summary(rows):
    out = {"pairs": len(rows), "n_avg": round(sum(r["n"] for r in rows) / len(rows), 1)}
    for k in KS:
        for who in ("model", "trend", "random"):
            out[f"{who}_hit{k}"] = round(sum(r[f"{who}_hit{k}"] for r in rows) / len(rows), 2)
    return out


def main():
    crits = sys.argv[1:] or ["k_export", "k_export_agent"]
    countries = store.countries(fetch=False)
    res = {}
    for c in crits:
        rows = run(c, countries)
        res[c] = {"summary": summary(rows), "pairs": rows}
        s = res[c]["summary"]
        print(f"\n== {c}: 표본 밖 {s['pairs']}개 구간, 평균 {s['n_avg']}개국")
        for k in KS:
            print(f"  TOP{k} 적중(평균): 모델 {s[f'model_hit{k}']} / 단순추세 {s[f'trend_hit{k}']} / 무작위 {s[f'random_hit{k}']}  (최대 {k})")
        for r in rows:
            print(f"  {r['fit']}년 기준 → {r['test']}: 모델 TOP3 {r['model_top3']} (실제 {r['model_top3_actual_rank']}등) | 실제 TOP3 {r['actual_top3']}")
    d = ROOT / "outputs" / "hit_rate"
    d.mkdir(parents=True, exist_ok=True)
    (d / "hit_rate.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
