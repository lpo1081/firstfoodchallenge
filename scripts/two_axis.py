"""두 축 사분면: 축 1 수출 유망도(한국 과자 수출 증가) × 축 2 현지 시장 성장성(UNIDO 과자류 실소비 = 현지 생산+수입−수출 증가).

- 둘 다 상위 1/3  → 수출 우선 진출
- 축 2만 상위     → 현지생산·인수 검토(한국에서 보내는 것보다 현지에서 만들어 파는 쪽)
- 축 1만 상위     → 수출 유지·확대(시장 자체 성장은 보통)
- 둘 다 아님      → 관망
나라마다 각 축 점수를 끌어올린 지표 3개(가중치 × 백분위)를 이유로 붙인다.

실행(비용 0, 먼저 study 실행 필요):
  .venv/bin/python -m kfood_scout study --study two_axis --no-fetch
  .venv/bin/python scripts/two_axis.py
결과: outputs/two_axis/two_axis.json, two_axis.md
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kfood_scout.config import ROOT

STUDY, CAT = "two_axis", "dry_confectionery"
AX = {"export": "k_export_agent", "local": "local_market"}
HIGH = 2 / 3


def load(crit):
    p = ROOT / "outputs" / "studies" / STUDY / "runs" / f"category={CAT}__criterion={crit}__method=rolling.json"
    r = json.loads(p.read_text())
    return r.get("result", r)


def reasons(res, iso, k=3):
    W, P = res["XX"], res["pct_now"].get(iso)
    if not P:
        return []
    names = {i["id"]: i["name"] for i in res["indicators"]}
    tot = sum(W.values()) or 1
    top = sorted(W, key=lambda i: -W[i] * P[i])[:k]
    return [f"{names[i]} 상위 {max(1, round(100 - P[i]))}%" for i in top]


def main():
    R = {a: load(c) for a, c in AX.items()}
    pos = {}
    for a, res in R.items():
        b = res["forecast_XX"]
        for i, c in enumerate(b):
            d = pos.setdefault(c["iso3"], {"iso3": c["iso3"], "name": c["name"], "existing": c["existing"]})
            d[f"{a}_pct"] = round(100 * (1 - i / len(b)), 1)   # 100 = 1위
            d[f"{a}_rank"] = i + 1
            d[f"{a}_n"] = len(b)
            d[f"{a}_top10_prob"] = c.get("prob", {}).get("top10")
            d[f"{a}_tier"] = c.get("tier")
            d[f"{a}_why"] = reasons(res, c["iso3"])
            if a == "export":
                d["kor_exports_usd"] = c["kor_exports_usd"]
            else:
                d["imports_usd"] = c.get("target_base_usd")
    rows = []
    for d in pos.values():
        e, l = d.get("export_pct"), d.get("local_pct")
        he, hl = e is not None and e >= 100 * HIGH, l is not None and l >= 100 * HIGH
        d["quadrant"] = ("수출 우선" if he and hl else "현지생산·인수 검토" if hl else "수출 유지·확대" if he
                         else "관망" if e is not None and l is not None else "한 축만 평가됨")
        rows.append(d)
    order = {"수출 우선": 0, "현지생산·인수 검토": 1, "수출 유지·확대": 2, "관망": 3, "한 축만 평가됨": 4}
    rows.sort(key=lambda d: (order[d["quadrant"]], -((d.get("export_pct") or 0) + (d.get("local_pct") or 0))))
    out = ROOT / "outputs" / "two_axis"
    out.mkdir(parents=True, exist_ok=True)
    (out / "two_axis.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    L = ["# 수출 유망도 × 현지 시장 성장성", "", "| 사분면 | 국가 | 기진출 | 수출축 순위 | 현지축 순위 | 한국 수출(백만$) | 현지 과자 실소비(UNIDO) | 수출축 이유 | 현지축 이유 |",
         "|---|---|---|---|---|---|---|---|---|"]
    f = lambda v: "-" if v is None else f"{v / 1e6:,.1f}"
    for d in rows:
        if d["quadrant"] in ("관망", "한 축만 평가됨"):
            continue
        L.append(f"| {d['quadrant']} | {d['name']} | {'O' if d['existing'] else ''} | {d.get('export_rank', '-')}/{d.get('export_n', '-')} | "
                 f"{d.get('local_rank', '-')}/{d.get('local_n', '-')} | {f(d.get('kor_exports_usd'))} | {f(d.get('imports_usd'))} | "
                 f"{', '.join(d.get('export_why', []))} | {', '.join(d.get('local_why', []))} |")
    (out / "two_axis.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
