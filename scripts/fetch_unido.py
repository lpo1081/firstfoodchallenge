"""UNIDO IDSB 과자류 실소비·생산 수집(무료, 키 없음, 약 110개국 × 2개 변수 → 국가당 1회 호출, 5분 안팎).
실행: .venv/bin/python scripts/fetch_unido.py   → data/store/external/ 에 저장(이후 재수집 안 함)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kfood_scout import store

YEARS = list(range(2005, 2024))
for name in ("unido_snack_consumption", "unido_snack_output"):
    df = store.external_series(name, YEARS, fetch=True)
    last = df[df.year >= 2020].iso3.nunique()
    print(f"{name}: {df.iso3.nunique()}개국, {len(df)}행, 2020년 이후 값 있는 나라 {last}개")
    for iso in ("PHL", "IDN", "IND", "VNM", "USA", "MNG"):
        s = df[df.iso3 == iso].sort_values("year")
        print(f"  {iso}: " + (", ".join(f"{y}:{v:,.0f}" for y, v in zip(s.year.tail(4), s.value.tail(4))) or "없음"))
