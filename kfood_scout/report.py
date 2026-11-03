"""결과물 생성: CSV, 마크다운 리포트, 대시보드용 JSON."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Criterion


def _fmt(x, nd=1):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def ranking_markdown(table, raw, pct, criterion: Criterion, category_name: str, as_of: int, top_n=15):
    core = criterion.indicators
    w = pd.Series(criterion.weights)
    w = w / w.sum()
    lines = [f"# {criterion.name_ko} × {category_name} — 유망국 순위 (기준연도 {as_of})", "",
             f"평가 대상 {len(table)}개국 · 지표별 백분위(0~100) 가중합", "",
             "| 지표 | 가중치 | 의미 |", "|---|---|---|"]
    for i in core:
        lines.append(f"| {i.name_ko} ({i.unit}) | {w[i.id]:.0%} | {' '.join(i.meaning.split())} |")
    lines += ["", "## TOP 3", ""]
    for iso in table.index[:3]:
        r = table.loc[iso]
        strong = pct.loc[iso, [i.id for i in core]].sort_values(ascending=False)
        bits = [f"{next(i.name_ko for i in core if i.id == k)} 상위 {100 - v:.0f}%" for k, v in strong.head(2).items()]
        lines.append(f"**{int(r['rank'])}. {r['name']} ({iso})** — 점수 {r['score']:.1f}. 강점: {', '.join(bits)}")
        lines.append("")
    hdr = "| 순위 | 국가 | 점수 | " + " | ".join(i.name_ko for i in core) + " | 결측 |"
    lines += ["## 상위 국가 상세 (괄호 안은 백분위)", "", hdr, "|" + "---|" * (len(core) + 4)]
    for iso in table.index[:top_n]:
        r = table.loc[iso]
        cells = [f"{_fmt(raw.loc[iso, i.id], 2)} ({_fmt(pct.loc[iso, i.id], 0)})" for i in core]
        lines.append(f"| {int(r['rank'])} | {r['name']} | {r['score']:.1f} | " + " | ".join(cells) +
                     f" | {r['missing'] or ''} |")
    return "\n".join(lines)


def validation_markdown(events, inverse, cands, criterion: Criterion, countries):
    nm = countries.set_index("iso3")["name"].to_dict()
    names = {i.id: i.name_ko for i in criterion.all_indicators()}
    L = ["# 역산 검증 — 롯데웰푸드 실제 진출국 vs 모델", "",
         "각 진출 건을 '진출연도-1' 데이터로 다시 돌린 결과입니다.", "",
         "| 진출국 | 연도 | 방식 | 역산 포함 | 모델 순위(기본 가중치) | 당시 모델 1위 | 당시 TOP3 |",
         "|---|---|---|---|---|---|---|"]
    for ev in events:
        rk = f"{ev['rank']} / {ev['n']}" if ev["rank"] else "평가 불가(데이터 부족)"
        L.append(f"| {ev['country_ko']} | {ev['year']} | {ev['mode']} | {'O' if ev.get('include', True) else 'X'} | "
                 f"{rk} | {nm.get(ev.get('top1'), '-')} | {', '.join(nm.get(x, x) for x in ev.get('top3', []))} |")
    L += ["", "## 실제 진출국 vs 모델 1위: 지표 차이가 가장 컸던 부분", ""]
    for ev in events:
        if ev["rank"] is None:
            continue
        g = ev["gap"].head(4)
        L.append(f"**{ev['country_ko']} {ev['year']}** (모델 1위 {nm.get(ev['top1'])}):")
        for _, r in g.iterrows():
            L.append(f"- {r['지표']}[{r['구분']}]: 실제국 {r['실제국_백분위']:.0f} vs 1위국 {r['모델1위_백분위']:.0f} "
                     f"(차이 {r['차이(실제-1위)']:+.0f})")
        L.append("")
    L += ["## 가중치 역산", "",
          f"{inverse['n_combinations']:,}개 가중치 조합을 전수 시도, 실제 진출 {inverse['n_events']}건의 평균 순위 백분위를 최대화.",
          "", "| 지표 | 기본 가중치 | 최적 | 설명가능 범위(상위 1% 조합 평균, 최소~최대) |", "|---|---|---|---|"]
    for k in inverse["best_weights"]:
        L.append(f"| {names[k]} | {inverse['default_weights'][k]:.0%} | {inverse['best_weights'][k]:.0%} | "
                 f"{inverse['robust_mean'][k]:.0%} ({inverse['robust_min'][k]:.0%}~{inverse['robust_max'][k]:.0%}) |")
    L += ["", f"실제 진출국의 평균 순위 백분위: 기본 가중치 {inverse['default_mean_percentile']:.0%} → "
              f"역산 가중치 {inverse['best_mean_percentile']:.0%} (100%=매번 1위)", "",
          "| 진출국 | 연도 | 기본 가중치 순위 | 역산 가중치 순위 |", "|---|---|---|---|"]
    for p in inverse["per_event"]:
        L.append(f"| {p['country_ko']} | {p['year']} | {p['rank_default']} / {p['n']} | {p['rank_inverse']} / {p['n']} |")
    L += ["", "## 신규 지표 후보 검토", "",
          "| 후보 지표 | 실제 진출국 평균 백분위 | 50 초과 사례 | 6번째 지표로 추가 시 설명력 개선 | 그때 가중치 |",
          "|---|---|---|---|---|"]
    for _, r in cands.iterrows():
        L.append(f"| {r['지표']} | {_fmt(r['실제국_평균백분위'], 0)} | {r['50초과_사례수']}/{r['사례수']} | "
                 f"{r['개선폭(%p)']:+.1f}%p | {r['추가시_가중치']:.0%} |")
    return "\n".join(L)


def dashboard_payload(table, raw, pct, criterion, category_name, as_of, events=None, inverse=None,
                      cands=None, countries=None, sources=None):
    core = criterion.indicators
    rows = []
    for iso in table.index:
        rows.append({"iso3": iso, "name": table.loc[iso, "name"], "region": table.loc[iso, "region"],
                     "pct": {i.id: (None if pd.isna(pct.loc[iso, i.id]) else round(float(pct.loc[iso, i.id]), 1))
                             for i in core},
                     "raw": {i.id: (None if pd.isna(raw.loc[iso, i.id]) else round(float(raw.loc[iso, i.id]), 3))
                             for i in core}})
    out = {"as_of": as_of, "category": category_name, "criterion": criterion.name_ko,
           "indicators": [{"id": i.id, "name": i.name_ko, "unit": i.unit, "weight": i.weight,
                           "meaning": " ".join(i.meaning.split()), "source": i.source,
                           "series": i.series or f"HS {i.flow}"} for i in core],
           "countries": rows, "sources": sources or []}
    if events is not None:
        nm = countries.set_index("iso3")["name"].to_dict()
        out["validation"] = {
            "events": [{"iso3": e["iso3"], "country_ko": e["country_ko"], "year": e["year"], "mode": e["mode"],
                        "include": e.get("include", True), "rank": e["rank"], "n": e["n"],
                        "top1": nm.get(e.get("top1")), "detail": e["detail"], "sources": e["sources"],
                        "gap": ([{"name": r["지표"], "kind": r["구분"],
                                  "actual": None if pd.isna(r["실제국_백분위"]) else round(float(r["실제국_백분위"])),
                                  "top1": None if pd.isna(r["모델1위_백분위"]) else round(float(r["모델1위_백분위"]))}
                                 for _, r in e["gap"].iterrows()] if e["rank"] else [])}
                       for e in events],
            "inverse": inverse,
            "candidates": cands.replace({np.nan: None}).to_dict(orient="records"),
        }
    return out


def write_outputs(outdir: Path, **files):
    outdir.mkdir(parents=True, exist_ok=True)
    for name, obj in files.items():
        p = outdir / name
        if isinstance(obj, pd.DataFrame):
            obj.to_csv(p, encoding="utf-8-sig")
        elif isinstance(obj, (dict, list)):
            p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=float))
        else:
            p.write_text(str(obj))


def write_dashboard(outdir: Path, payload: dict) -> Path:
    tpl = (Path(__file__).parent / "dashboard_template.html").read_text()
    js = json.dumps(payload, ensure_ascii=False, default=float).replace("</", "<\\/")
    p = outdir / "dashboard.html"
    p.write_text(tpl.replace("__DATA__", js))
    return p
