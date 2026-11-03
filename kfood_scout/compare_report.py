"""comparison.json → 비교 대시보드 HTML. 결론 문장(findings)·부제는 인자로 주입."""
from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT

TEMPLATE = Path(__file__).with_name("compare_template.html")
SOURCES = [
    "UN Comtrade (comtradeapi.un.org): 한국 상대국별 수출, 각국 대세계 수입, HS 2017 6단위, USD",
    "World Bank WDI (api.worldbank.org): 인구, 1인당 가계소비, 유소년 비중, 도시화율, 1인당 GDP(PPP)",
    "카테고리별 매출: 메리츠증권 롯데웰푸드 리포트(2025-02-12), 2024년 잠정",
]


def write(study_name: str, findings: list[str] | None = None, subtitle: str = "", out: Path | None = None) -> Path:
    d = ROOT / "outputs" / "studies" / study_name
    data = json.loads((d / "comparison.json").read_text())
    data.update({"findings": findings or [], "subtitle": subtitle, "sources": SOURCES})
    out = out or d / "comparison.html"
    out.write_text(TEMPLATE.read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False, default=float)), encoding="utf-8")
    return out
