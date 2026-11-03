"""K-푸드 수출 유망국 스카우트 CLI

  python -m kfood_scout fetch    # 원천 데이터 수집 → data/panel_<category>.csv
  python -m kfood_scout score    # 기준연도 스코어링 → outputs/
  python -m kfood_scout validate # 롯데웰푸드 진출국 역산 검증 → outputs/
  python -m kfood_scout all      # 위 3단계 + 대시보드
  python -m kfood_scout plan    --study lotte_top5   # 남은 Comtrade 호출 수
  python -m kfood_scout study   --study lotte_top5   # 수집(부족분만) → 축 조합별 계산 → 비교
  python -m kfood_scout compare --study lotte_top5   # 저장된 결과로 비교만 다시

공통 옵션: --category dry_confectionery --criterion market_growth --as-of 2023
가중치 덮어쓰기: --weights import_market_cagr=0.4,population_size=0.05
"""
from __future__ import annotations

import argparse
import sys

from . import data, report, validation
from .config import ROOT, load_categories, load_criterion, load_entries
from .scoring import score

SOURCES = [
    "UN Comtrade Database (comtradeapi.un.org), HS 2017 6단위, 보고국 대세계 수입·수출액(USD)",
    "World Bank World Development Indicators (api.worldbank.org)",
]


def parse_weights(s: str | None) -> dict | None:
    if not s:
        return None
    return {k: float(v) for k, v in (kv.split("=") for kv in s.split(","))}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kfood_scout")
    ap.add_argument("cmd", choices=["fetch", "score", "validate", "dashboard", "all", "plan", "study", "compare"])
    ap.add_argument("--category", default="dry_confectionery")
    ap.add_argument("--criterion", default="market_growth")
    ap.add_argument("--entries", default="lotte_wellfood")
    ap.add_argument("--as-of", type=int, default=2023)
    ap.add_argument("--start", type=int, default=1987)
    ap.add_argument("--weights")
    ap.add_argument("--grid-step", type=float, default=0.05)
    ap.add_argument("--study", default="lotte_top5")
    ap.add_argument("--only", help="예: category=ice_cream")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd in ("plan", "study", "compare"):
        return run_study_cmd(a)

    cats = load_categories()
    crit = load_criterion(a.criterion)
    w = parse_weights(a.weights)
    if w:
        for i in crit.indicators:
            if i.id in w:
                i.weight = w[i.id]
    entries = load_entries(a.entries)
    cat_name = cats[a.category]["name_ko"]
    out = ROOT / "outputs" / f"{a.category}__{a.criterion}"

    if a.cmd in ("fetch", "all"):
        data.build_panel(a.category, cats, crit, start=a.start, end=a.as_of + 1,
                         mirror_iso3={e["iso3"]: e["year"] for e in entries["entries"] if e.get("include", True)})
    panel, countries = data.load_panel(a.category), data.load_countries()

    payload = None
    if a.cmd in ("score", "all", "dashboard"):
        table, raw, pct = score(panel, countries, crit, a.category, a.as_of)
        report.write_outputs(out, **{
            f"ranking_{a.as_of}.csv": table, f"indicators_raw_{a.as_of}.csv": raw,
            f"indicators_pct_{a.as_of}.csv": pct,
            f"ranking_{a.as_of}.md": report.ranking_markdown(table, raw, pct, crit, cat_name, a.as_of)})
        payload = report.dashboard_payload(table, raw, pct, crit, cat_name, a.as_of, sources=SOURCES)
        print(table.head(10)[["name", "score"]].to_string())

    if a.cmd in ("validate", "all", "dashboard"):
        events, inv, cands = validation.run(panel, countries, crit, a.category, entries, grid_step=a.grid_step)
        report.write_outputs(out, **{"validation.md": report.validation_markdown(events, inv, cands, crit, countries),
                                     "validation_inverse.json": inv, "validation_candidates.csv": cands})
        for ev in events:
            if ev["rank"]:
                ev["gap"].to_csv(out / f"gap_{ev['iso3']}_{ev['year']}.csv", encoding="utf-8-sig")
        if payload is not None:
            payload = report.dashboard_payload(table, raw, pct, crit, cat_name, a.as_of, events, inv, cands,
                                               countries, SOURCES)
        print(f"역산 가중치: { {k: float(v) for k, v in inv['best_weights'].items()} }  (평균 백분위 {inv['default_mean_percentile']:.2f} → "
              f"{inv['best_mean_percentile']:.2f})")

    if payload is not None:
        report.write_outputs(out, **{"dashboard_data.json": payload})
        print("대시보드:", report.write_dashboard(out, payload))
    return 0


def run_study_cmd(a):
    import json as _json

    from . import compare, study
    if a.cmd == "plan":
        p = study.plan(a.study)
        for r in p:
            print(f"{r['run']}: HS {len(r['hs'])}개 × {r['flows']} → 남은 호출 {r['pending_calls']}")
        print("합계", sum(r["pending_calls"] for r in p), "회 (공개 API ~200회/시간)")
        return 0
    if a.cmd == "study":
        only = dict(kv.split("=") for kv in a.only.split(",")) if a.only else None
        study.run_study(a.study, fetch=not a.no_fetch, only=only, force=a.force)
    c = compare.compare(a.study)
    for r in c["runs"]:
        if r["error"]:
            print(r["run_id"], "불가:", r["error"]); continue
        s, v = r["summary"], r.get("vs_baseline", {})
        print(r["run_id"], "| n", s["n_windows"], "| 그룹추세", s["group_trend"], "| XX", s["XX_groups"],
              "| 표본밖", round(s["oos_X_prev"] or 0, 3), "| TOP5", s["top5_new_XX"],
              "| vs 기준 순위상관", v.get("forecast_rank_corr"), "겹침", v.get("top10_overlap"))
    if c.get("consensus"):
        print("통합(매출 가중) TOP10 신규:", [x["name"] for x in c["consensus"] if not x["existing"]][:10])
    print("저장:", ROOT / "outputs" / "studies" / a.study / "comparison.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
