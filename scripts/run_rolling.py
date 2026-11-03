"""롤링 역산 실행: python scripts/run_rolling.py [forecast_year]
결과: outputs/dry_confectionery__k_export/rolling.json"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kfood_scout import data, rolling
from kfood_scout.config import ROOT, load_criterion, load_entries

fy = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
crit = load_criterion(sys.argv[2] if len(sys.argv) > 2 else "k_export")  # 예: k_export_agent
existing = {e["iso3"] for e in load_entries()["entries"]}
panel, countries = data.load_panel("dry_confectionery"), data.load_countries()
out = rolling.run(panel, countries, crit, "dry_confectionery", starts=(2012, 2015, 2018, 2021), forecast_year=fy, existing=existing)
d = ROOT / "outputs" / f"dry_confectionery__{crit.id}"
d.mkdir(parents=True, exist_ok=True)
(d / "rolling.json").write_text(json.dumps(out, ensure_ascii=False, default=float), encoding="utf-8")
for w in out["windows"]:
    print(w["t"], "→", w["t"] + w["h"], "n=", w["n"], "rho=", round(w["rho_robust"], 3), w["groups"])
print("표본밖:", [(o["fit"], o["test"], round(o["X_prev"], 3), round(o["equal"], 3), round(o["momentum"], 3)) for o in out["out_of_sample"]])
print("XX 검증:", out["xx_test"])
print("XX:", out["XX"])
print("TOP10(XX, 기진출 제외):", [c["name"] for c in out["forecast_XX"] if not c["existing"]][:10])
