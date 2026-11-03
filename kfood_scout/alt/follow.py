"""방법 3. 일본 과자 추적 (경쟁국 수출 증가국).

한국 과자의 직접 경쟁인 일본 건과(포키·킷캣재팬 등)의 나라별 수출이 최근 5년 가장 많이 늘어난 나라 =
경쟁국이 '아시아 수입 과자 수요'를 이미 증명한 곳. 그중 한국 수출이 일본보다 작은 나라는 따라 들어갈 여지가 크다.
데이터: UN Comtrade, 일본(392)의 상대국별 수출, 카테고리 HS 코드 전부.
처음 한 번 받아 data/store/comtrade_JPN_X/ 에 저장(COMTRADE_API_KEY 있으면 정식 API).
"""
from __future__ import annotations

import pandas as pd

from .common import STORE, avg_last, trade, wide

def fetch(cfg: dict, hs: str) -> pd.DataFrame:
    from ..sources import comtrade  # 네트워크가 필요할 때만 불러옴
    f = cfg["methods"]["follow"]
    rows = []
    for period in comtrade._periods(list(range(2005, cfg["now_year"] + 1))):
        for r in comtrade._get({"period": period, "cmdCode": hs, "flowCode": "X", "reporterCode": str(f["reporter_m49"])}):
            iso = r.get("partnerISO")
            if str(r.get("partnerCode")) == "0" or not iso or iso.startswith(("X", "_")) or iso == "W00":
                continue
            rows.append({"iso3": iso, "year": int(r["refYear"]), "value": r.get("primaryValue")})
    d = pd.DataFrame(rows, columns=["iso3", "year", "value"]).dropna()
    return d.groupby(["iso3", "year"], as_index=False).value.sum()


def load(cfg: dict) -> pd.DataFrame:
    """HS 코드 1개 = 파일 1개(data/store/comtrade_JPN_X/<hs>.csv). 없는 코드만 받는다."""
    d = STORE / f"comtrade_{cfg['methods']['follow']['reporter_iso3']}_X"
    frames = []
    for hs in cfg["hs"]:
        p = d / f"{hs}.csv"
        if not p.exists():
            d.mkdir(parents=True, exist_ok=True)
            fetch(cfg, hs).to_csv(p, index=False)
        frames.append(pd.read_csv(p)[["iso3", "year", "value"]])
    return wide(pd.concat(frames).astype({"iso3": str, "year": int, "value": float}))


def run(cfg: dict, cand: list[str], universe: list[str]) -> dict:
    f = cfg["methods"]["follow"]
    n = cfg["smooth_years"]
    jp = load(cfg)
    kor = trade("KOR_X", cfg["hs"])
    j0, j1 = avg_last(jp, f["from_year"], n), avg_last(jp, f["to_year"], n)
    k1 = avg_last(kor, f["to_year"], n)
    d = pd.DataFrame({"jp_before": j0, "jp_now": j1}).fillna(0)
    d["jp_increase"] = d.jp_now - d.jp_before
    d["kor_now"] = k1.reindex(d.index).fillna(0)
    pool = d.loc[[c for c in cand if c in d.index]]
    ranked = pool[pool.jp_increase > 0].sort_values("jp_increase", ascending=False)
    return {
        "method": "follow",
        "window": f"{f['from_year'] - n + 1}~{f['from_year']} 평균 → {f['to_year'] - n + 1}~{f['to_year']} 평균",
        "ranking": [{"iso3": c, "jp_increase_musd": round(r.jp_increase / 1e6, 2), "jp_now_musd": round(r.jp_now / 1e6, 2),
                     "jp_growth_pct": (round((r.jp_now / r.jp_before - 1) * 100) if r.jp_before > 0 else None),
                     "kor_now_musd": round(r.kor_now / 1e6, 2), "kor_below_japan": bool(r.kor_now < r.jp_now)}
                    for c, r in ranked.iterrows()],
    }
