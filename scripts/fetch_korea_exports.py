import pandas as pd
from kfood_scout.config import load_categories
from kfood_scout.data import DATA, panel_path
from kfood_scout.sources import comtrade

CAT = "dry_confectionery"
KEY = f"CT:{CAT}:KOR_X"

hs = list(load_categories()[CAT]["hs_codes"].keys())
df = comtrade.fetch_korea_exports(hs, range(2005, 2025))
df.to_csv(DATA / f"comtrade_kor_exports_hs_{CAT}.csv", index=False)
agg = df.groupby(["iso3", "year"], as_index=False)["value"].sum()
agg["series"] = KEY
panel = pd.read_csv(panel_path(CAT))
panel = pd.concat([panel[panel.series != KEY], agg], ignore_index=True)
panel.to_csv(panel_path(CAT), index=False)
print("rows", len(agg), "partners", agg.iso3.nunique())
