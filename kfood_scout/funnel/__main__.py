"""통합 진출국 선정 깔때기 실행. API 비용 0원(유료 API 호출 없음).

  .venv/bin/python -m kfood_scout.funnel                 # 처음 한 번 공개 미러(물가·환율·물류지수·국가 좌표)를 받고 저장
  .venv/bin/python -m kfood_scout.funnel --no-fetch      # 저장분만
  .venv/bin/python -m kfood_scout.funnel --category dry_confectionery   # 다른 품목(config/categories.yaml)
결과: outputs/funnel/<품목>/report.md, result.json
"""
import argparse
import json

from ..config import ROOT, load_categories
from .core import load_checklist, load_protocol, run_all
from .data import build
from .report import ko, to_md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--category", default=None)
    ap.add_argument("--out", default="outputs/funnel")
    a = ap.parse_args()
    proto = load_protocol()
    if a.category:
        cat = load_categories()[a.category]
        proto["category"] = {"id": a.category, "name_ko": cat["name_ko"], "hs_codes": [str(h) for h in cat["hs_codes"]]}
    T, cty = build(proto["category"]["hs_codes"], proto["as_of"], fetch=not a.no_fetch)
    R = run_all(T, cty, proto)
    md = to_md(R, T, cty, proto, load_checklist())
    od = ROOT / a.out / proto["category"]["id"]
    od.mkdir(parents=True, exist_ok=True)
    (od / "report.md").write_text(md, encoding="utf-8")
    b = R["base"]
    out = {
        "category": proto["category"], "protocol": proto["id"], "top3": R["top"], "top3_ko": [ko(c, cty) for c in R["top"]],
        "funnel": {"pool": len(R["pool"]), "stage1": len(R["s1"]), "stage2": len(b["s2"]), "stage3": len(b["s3"]),
                   "stage4": len(b["s4"]), "stage5": len(b["s4"]) - len(R["excluded"])},
        "fate": {c: dict(f, name=ko(c, cty)) for c, f in R["fate"].items()},
        "final": R["final"].round(2).to_dict(), "mc_top3_pct": R["mc_keep"].round(1).to_dict(), "mc_same3_pct": R["mc_same3"],
        "shock_top3": R["top3_shock"], "shock_npv": R["npv_shock"], "shocks": R["shocks"],
        "scores": {c: {"attractiveness": float(b["attr"][c]), "ability": float(b["abil"][c]), "safety": float(b["safety"][c]),
                       "attr_groups": b["attrG"].loc[c].round(1).to_dict(), "ability_groups": b["abilG"].loc[c].round(1).to_dict()}
                   for c in R["s1"]},
        "economics": {c: {k: v for k, v in R["econ"][c].items() if k != "years"} | {"grade": R["grade"][c]} for c in b["s3"]},
        "indicators": T.reindex(R["pool"]).round(4).astype(object).where(T.reindex(R["pool"]).notna(), None).to_dict(orient="index"),
        "crp_fit": R["crp_fit"],
    }
    (od / "result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(md)
    print(f"\n저장: {od}")


if __name__ == "__main__":
    main()
