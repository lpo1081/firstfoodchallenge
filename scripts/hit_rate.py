"""적중률: 과거 각 시점에 모델이 뽑은 TOP-k 중 몇 개가 실제로 3년 뒤 '수출 증가 TOP-k'에 들었나.

2026-11-03 외부 검토 반영(과대평가 방지):
- 정답 2종: abs(증가액, 큰 시장 유리) / log(증가율, 중간·신흥 시장도 맞혀야 함)
- 국가 범위: all(전체) / ex_big(미국·중국 제외 — 미국이 매 구간 1위라 적중 수를 부풀리던 문제)
  / tier:큰 시장·중간 시장·작은 시장(그 시점 한국 수출 규모 3분위, 체급 안에서만 순위 비교)
- 대조군 4종: 모델 / 단순 추세(직전 3년 증가 순) / 큰 시장 순(그 시점 한국 수출 규모 순) / 무작위
- 요약 3종:
  all    = 1년 간격 7구간 평균(구간끼리 겹쳐서 실제 독립 시험은 2~3번뿐 — 참고용)
  indep  = 서로 안 겹치는 구간만(2012→15·2015→18·2018→21 시점에서 각각 3년 뒤 예측)
  sealed = 봉인 구간(2018년 가중치 → 2021→24 예측). 에이전트 지표 선택 때 보지 않은 유일한 구간.
           k_export_agent 는 `agent test` 를 2018년까지 창으로 다시 돌리고 adopt 한 뒤라야 의미가 있다
           (기준 파일의 selection.last_start 로 확인).

실행(API 비용 없음, 저장된 데이터만 사용):
  .venv/bin/python scripts/hit_rate.py                  # k_export, k_export_agent × abs/log × all/ex_big
  .venv/bin/python scripts/hit_rate.py --existing       # 롯데 기진출국끼리만 순위 비교(참고용)
  .venv/bin/python scripts/hit_rate.py --exclude USA,CHN,JPN   # 제외국 바꾸기
결과: outputs/hit_rate/hit_rate.json(또는 hit_rate_existing.json)과 화면 요약
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 저장소 루트에서 kfood_scout 를 찾도록

import pandas as pd

from kfood_scout import rolling, store
from kfood_scout.agent import evaluate as ev
from kfood_scout.agent import loop
from kfood_scout.config import ROOT, criterion_from_dict, load_criterion_raw, load_entries

CAT = "dry_confectionery"
KS = (3, 5, 10)
H = 3
SEAL_FIT = loop.SEAL_FROM - H          # 2018: 봉인 구간을 맞히는 가중치의 시점
INDEP_FITS = (SEAL_FIT - 2 * H, SEAL_FIT - H, SEAL_FIT)   # 2012, 2015, 2018
WHO = ("model", "trend", "size", "random")


def SIZE_COL(P):
    return "korea_exports_size" if "korea_exports_size" in P else "import_market_size"


def windows(crit_id, kind, countries):
    raw = load_criterion_raw(crit_id)
    raw["target"] = dict(raw.get("target", {}), kind=kind)
    crit = criterion_from_dict(raw)
    panel = loop.panel_for(CAT, raw, fetch=False, log=lambda *a: None)
    wins = ev._windows(panel, countries, crit, CAT, range(2012, loop.SEAL_FROM + 1), 8000, 0)
    ev._fit_all(wins, 8000, 0)
    return wins, raw


def pairs(wins, name, only=None, exclude=(), tier=None):
    rows = []
    for t in sorted(wins):
        s = t + H
        if s not in wins:
            continue
        P, y = wins[s]["pct"], wins[s]["y"]
        tr = rolling.tiers_of(P[SIZE_COL(P)], 3) if tier else None
        keep = [c for c in P.index if c not in exclude and (not only or c in only) and (not tier or tr[c] == tier)]
        P, y = P.loc[keep], y.loc[keep]  # 지표 백분위는 전체 국가 기준 그대로, 순위 비교만 부분집합
        n = len(y)
        preds = {
            "model": pd.Series(P.to_numpy() @ wins[t]["w"], index=P.index),
            "trend": wins[t]["y"].reindex(P.index),            # 직전 3년(t→s) 정답 = 단순 추세
            "size": P[SIZE_COL(P)],  # 큰 시장 순으로 찍기(한국 수출 규모, 없으면 수입시장 규모)
        }
        rec = {"fit": t, "test": f"{s}->{s + H}", "n": n, "sealed": t == SEAL_FIT}
        rec["rank_corr"] = round(float(preds["model"].rank().corr(y.rank())), 3)
        rec["size_rank_corr"] = round(float(preds["size"].rank().corr(y.rank())), 3) if preds["size"] is not None else None
        for k in [k for k in KS if k < n]:
            act = set(y.nlargest(k).index)
            for who, p in preds.items():
                if p is not None:
                    rec[f"{who}_hit{k}"] = len(set(p.dropna().nlargest(k).index) & act)
            rec[f"random_hit{k}"] = round(k * k / n, 2)
        top = preds["model"].nlargest(3).index
        ar = y.rank(ascending=False)
        rec["model_top3"] = [name.get(c, c) for c in top]
        rec["model_top3_actual_rank"] = [int(ar[c]) for c in top]
        rec["actual_top3"] = [name.get(c, c) for c in y.nlargest(3).index]
        rows.append(rec)
    return rows


def summary(rows):
    if not rows:
        return None
    out = {"pairs": len(rows), "n_avg": round(sum(r["n"] for r in rows) / len(rows), 1),
           "rank_corr": round(sum(r["rank_corr"] for r in rows) / len(rows), 3)}
    sc = [r["size_rank_corr"] for r in rows if r.get("size_rank_corr") is not None]
    if sc:
        out["size_rank_corr"] = round(sum(sc) / len(sc), 3)
    for k in KS:
        for who in WHO:
            v = [r[f"{who}_hit{k}"] for r in rows if f"{who}_hit{k}" in r]
            if len(v) == len(rows):
                out[f"{who}_hit{k}"] = round(sum(v) / len(v), 2)
    return out


def verdict(s):
    """모델이 '큰 시장 순'과 '단순 추세'를 모두 이겼는지 한 줄로."""
    if not s:
        return "구간 없음"
    m, t, z = s.get("model_hit3"), s.get("trend_hit3"), s.get("size_hit3")
    if m is None:
        return "-"
    beat = [n for n, v in (("단순추세", t), ("큰시장순", z)) if v is not None and m > v]
    lose = [n for n, v in (("단순추세", t), ("큰시장순", z)) if v is not None and m < v]
    return ("우위: " + ",".join(beat) if beat else "") + (" / 열위: " + ",".join(lose) if lose else "") or "동률"


def main():
    argv = sys.argv[1:]
    exclude = ("USA", "CHN")
    if "--exclude" in argv:
        exclude = tuple(argv[argv.index("--exclude") + 1].split(","))
        argv = argv[:argv.index("--exclude")] + argv[argv.index("--exclude") + 2:]
    crits = [a for a in argv if not a.startswith("--")] or ["k_export", "k_export_agent"]
    only = {e["iso3"] for e in load_entries()["entries"]} if "--existing" in argv else None
    countries = store.countries(fetch=False)
    name = countries.set_index("iso3")["name"].to_dict()
    res = {"exclude": list(exclude), "seal_fit": SEAL_FIT, "indep_fits": list(INDEP_FITS), "criteria": {}}
    print(f"봉인 구간: {SEAL_FIT}년 가중치 → {SEAL_FIT + H}->{SEAL_FIT + 2 * H}, 독립 구간: {list(INDEP_FITS)}")
    for c in crits:
        sel = load_criterion_raw(c).get("selection", {})
        sealed_ok = not c.endswith("_agent") or sel.get("last_start", 9999) <= SEAL_FIT  # 사람이 정한 지표 세트는 선택 누수 없음
        res["criteria"][c] = {"sealed_valid": sealed_ok, "scenarios": {}}
        if not sealed_ok:
            print(f"\n!! {c}: 지표 선택이 봉인 구간을 본 상태(selection.last_start={sel.get('last_start')}). "
                  f"sealed 결과는 무효 — agent test(2018까지) → adopt 를 다시 돌린 뒤 실행하세요.")
        for kind in ("abs", "log"):
            wins, _ = windows(c, kind, countries)
            scen = [("all", (), None), ("ex_big", exclude, None)] + \
                   [(f"tier:{t}", (), t) for t in rolling.TIER_NAMES[3]] * (not only)
            for univ, exc, tier in scen:
                rows = pairs(wins, name, only, exc, tier)
                sm = {"all": summary(rows),
                      "indep": summary([r for r in rows if r["fit"] in INDEP_FITS]),
                      "sealed": summary([r for r in rows if r["sealed"]])}
                res["criteria"][c]["scenarios"][f"{kind}/{univ}"] = {"summary": sm, "pairs": rows}
                print(f"\n== {c} | 정답 {kind} | {tier or ('전체' if univ == 'all' else '제외 ' + ','.join(exc))}"
                      f"{' | 기진출국만' if only else ''}")
                print("   요약     구간  국가  순위상관(모델/큰시장)  TOP3 적중 모델/추세/큰시장/무작위   TOP10 적중 모델/추세/큰시장   판정(TOP3)")
                for lab, s in sm.items():
                    if not s:
                        continue
                    print(f"   {lab:7s} {s['pairs']:4d} {s['n_avg']:5.0f}   {s['rank_corr']:+.2f} / {s.get('size_rank_corr', float('nan')):+.2f}"
                          f"            {s.get('model_hit3')}/{s.get('trend_hit3')}/{s.get('size_hit3')}/{s.get('random_hit3')}"
                          f"            {s.get('model_hit10', '-')}/{s.get('trend_hit10', '-')}/{s.get('size_hit10', '-')}"
                          f"     {verdict(s)}")
                for r in rows * (tier is None):
                    tag = " [봉인]" if r["sealed"] else ""
                    print(f"   {r['fit']}→{r['test']}{tag}: 모델 TOP3 {r['model_top3']} (실제 {r['model_top3_actual_rank']}등) | 실제 {r['actual_top3']}")
    d = ROOT / "outputs" / "hit_rate"
    d.mkdir(parents=True, exist_ok=True)
    stem = ("hit_rate_existing" if only else "hit_rate") + ("" if crits == ["k_export", "k_export_agent"] else "__" + "_".join(crits))
    (d / f"{stem}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
