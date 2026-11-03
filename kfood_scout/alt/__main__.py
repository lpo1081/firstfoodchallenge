"""다른 방법들로 진출국 찾기 + 기존 3대 기준 결과와 합의 보기.

실행: python -m kfood_scout.alt [--category dry_confectionery]
결과: outputs/alt_methods/result.json, report.md

새 방법을 붙이려면: kfood_scout/alt/<이름>.py 에 run(cfg, cand, universe) -> {"ranking": [{"iso3": ...}, ...]} 를 만들고
아래 METHODS 에 한 줄, config/alt/methods.yaml 의 methods 에 블록 하나를 추가한다. 기존 방법·기존 모델은 건드리지 않는다.
"""
from __future__ import annotations

import argparse
import json

from ..config import ROOT
from . import analog, follow, gap
from .common import candidates, load_cfg, names, save

METHODS = {          # 이름 → 모듈. 순서 = 보고서 순서
    "analog": analog,
    "gap": gap,
    "follow": follow,
}


def base_ranking() -> list[str]:
    """기존 3대 기준 모델 순위(읽기만). 맥북 실행 결과가 있으면 그것, 없으면 저장소 스냅샷."""
    for p in (ROOT / "outputs" / "three_criteria" / "ranking.json", ROOT / "results" / "three_criteria" / "ranking.json"):
        if p.exists():
            return [r["iso3"] for r in json.loads(p.read_text())["ranking"]]
    return []


def consensus(results: dict, base: list[str], top_n: int, cand: list[str]) -> list[dict]:
    """나라마다 몇 개 방법의 TOP N 에 들었는지. 같으면 평균 순위가 높은 나라가 위."""
    lists = {"base": [c for c in base if c in cand]}
    lists.update({k: [r["iso3"] for r in v["ranking"]] for k, v in results.items()})
    rows = []
    for c in cand:
        ranks = {k: (l.index(c) + 1 if c in l else None) for k, l in lists.items()}
        hits = [k for k, r in ranks.items() if r is not None and r <= top_n]
        top3 = [k for k, r in ranks.items() if r is not None and r <= 3]
        known = [r for r in ranks.values() if r is not None]
        if not hits:
            continue
        rows.append({"iso3": c, "n_top": len(hits), "n_top3": len(top3), "methods_top": hits, "ranks": ranks,
                     "avg_rank": round(sum(known) / len(known), 1)})
    rows.sort(key=lambda r: (-r["n_top"], -r["n_top3"], r["avg_rank"]))
    return rows


LABEL = {"base": "기존 3대 기준"}


def report(cfg, results, cons, excluded, base) -> str:
    nm = names()
    k = lambda c: nm.get(c, c)  # noqa: E731
    lab = dict(LABEL, **{m: cfg["methods"][m]["name_ko"] for m in results})
    n = cfg["top_n"]
    L = [f"# 다른 방법으로 찾은 진출국 ({cfg['category_name_ko']}, {cfg['now_year']}년 기준)", ""]
    top = cons[:3]
    L.append("## 결론")
    L.append(f"- 방법 {len(results) + 1}개(기존 모델 포함) 중 가장 많은 방법이 TOP{n}에 올린 나라: "
             + ", ".join(f"{k(r['iso3'])}({r['n_top']}/{len(results) + 1})" for r in top))
    L.append("")
    L.append(f"## 나라별 합의표 (숫자 = 그 방법에서의 순위, TOP{n} 밖은 –)")
    keys = ["base"] + list(results)
    L.append("| 나라 | " + " | ".join(lab[x] for x in keys) + f" | TOP{n} 든 방법 수 |")
    L.append("|---" * (len(keys) + 2) + "|")
    for r in cons[:15]:
        cells = [str(r["ranks"][x]) if r["ranks"][x] and r["ranks"][x] <= n else "–" for x in keys]
        L.append(f"| {k(r['iso3'])} | " + " | ".join(cells) + f" | {r['n_top']} |")
    L.append("")

    a = results.get("analog")
    if a:
        L.append(f"## 방법 1. {lab['analog']}")
        L.append("한국 과자 수출이 5년 만에 200만 달러 미만에서 400만 달러 이상(4배 이상)으로 뛴 '이륙' 사례: "
                 + ", ".join(f"{k(c['iso3'])} {c['year']}년({c['start_musd']}→{c['end_musd']}백만$)" for c in a["cases"]))
        L.append("이륙 직전 이 나라들의 모습(지표 10개, 그해 나라들 사이 백분위)과 지금 가장 닮은 나라. 닮음 점수 = 100 − 평균 차이.")
        for i, r in enumerate(a["ranking"][:n], 1):
            L.append(f"{i}. {k(r['iso3'])} {r['score']}점 (가장 닮은 사례 {r['nearest_case']})")
        L.append("")
    g = results.get("gap")
    if g:
        L.append(f"## 방법 2. {lab['gap']}")
        c = g["coef"]
        L.append(f"무역 중력모형(PPML, {g['n_countries']}개국): 수입시장 1% 클수록 한국 수출 {c['log_import_size']:.2f}% ↑, "
                 f"거리 1% 멀수록 {abs(c['log_distance']):.2f}% ↓, FTA 있으면 ×{2.718 ** c['fta']:.1f}배. "
                 f"실제와 기대치 일치도(R²) {g['fit_r2']}.")
        for i, r in enumerate(g["ranking"][:n], 1):
            L.append(f"{i}. {k(r['iso3'])}: 기대 {r['expected_musd']}백만$ vs 실제 {r['actual_musd']}백만$ "
                     f"→ 미실현 {r['gap_musd']}백만$ (기대치의 {r['actual_vs_expected_pct']:.0f}%만 실현)")
        L.append("")
    f = results.get("follow")
    if f:
        L.append(f"## 방법 3. {lab['follow']}")
        L.append(f"일본 과자 수출 증가({f['window']}).")
        for i, r in enumerate(f["ranking"][:n], 1):
            gr = f"+{r['jp_growth_pct']}%" if r["jp_growth_pct"] is not None else "신규"
            L.append(f"{i}. {k(r['iso3'])}: 일본 +{r['jp_increase_musd']}백만$({gr}, 현재 {r['jp_now_musd']}) / "
                     f"한국 현재 {r['kor_now_musd']}백만$" + (" ← 한국이 일본보다 작음" if r["kor_below_japan"] else ""))
        L.append("")
    L.append("## 후보에서 뺀 나라 (기존 모델과 같은 규칙)")
    for c, w in sorted(excluded.items()):
        L.append(f"- {k(c)}: {', '.join(w)}")
    L.append("")
    L.append("규칙 파일: config/alt/methods.yaml (결과 보기 전 고정). 기존 모델 결과는 읽기만 함.")
    return "\n".join(L)


def run(category: str | None = None, only: list[str] | None = None, log=print) -> dict:
    cfg = load_cfg(category)
    cand, excluded, universe = candidates(cfg)
    log(f"[alt] {cfg['category_name_ko']}: 전체 {len(universe)}개국, 후보 {len(cand)}개국")
    results = {}
    for name, mod in METHODS.items():
        if only and name not in only:
            continue
        log(f"[alt] {cfg['methods'][name]['name_ko']}")
        results[name] = mod.run(cfg, cand, universe)
    base = base_ranking()
    cons = consensus(results, base, cfg["top_n"], cand)
    out = {"category": cfg["category"], "now_year": cfg["now_year"], "candidates": cand, "excluded": excluded,
           "base_ranking": base, "methods": results, "consensus": cons}
    save("result.json", out)
    save("report.md", report(cfg, results, cons, excluded, base))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="다른 방법으로 진출국 찾기")
    ap.add_argument("--category", default=None)
    ap.add_argument("--only", nargs="*", help="일부 방법만: analog gap follow")
    a = ap.parse_args(argv)
    r = run(a.category, a.only)
    nm = names()
    print("합의 상위:", ", ".join(f"{nm.get(x['iso3'], x['iso3'])}({x['n_top']})" for x in r["consensus"][:5]))
    print("저장:", ROOT / "outputs" / "alt_methods")


if __name__ == "__main__":
    main()
