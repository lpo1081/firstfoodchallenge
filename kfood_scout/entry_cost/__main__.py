"""python -m kfood_scout.entry_cost [--out outputs/entry_cost]"""
import argparse
import json
from pathlib import Path

from .model import ROOT, load, run, sensitivity
from .report import to_md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/entry_cost")
    a = ap.parse_args()
    P, C = load()
    panel = {c["iso3"]: c for c in json.load(open(ROOT / P["benefit"]["panel"]))["countries"]}
    res = run(P, C, panel)
    ref = run(P, C, panel, isos=P.get("reference") or [])
    sens = sensitivity(P, C, panel)
    od = ROOT / a.out; od.mkdir(parents=True, exist_ok=True)
    json.dump({"ranking": res, "reference": ref, "sensitivity": sens}, open(od / "result.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=float)
    md = to_md(P, C, res, sens, ref)
    open(od / "report.md", "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    main()
