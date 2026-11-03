"""TOP3 나라별 비즈니스 임팩트: 롯데 기회 규모(원) + 진입 방식. API 호출 없음, 비용 0원.

계산(나라마다):
  과자 수입시장 N년 뒤 = 2024 수입시장 x (1 + 수입시장 5년 성장률)^N
  한국 과자 수출 증가 = N년 뒤 수입시장 x 한국산 비중 - 2024 한국 수출
     기본: 한국산 비중이 지금 그대로
     추세: 한국산 비중이 지난 5년 변화 속도로 계속 움직임
  롯데 기회 = 한국 증가분 x 롯데 몫
  점유율 1%p 가치 = N년 뒤 수입시장 x 1%
"""
import json, math, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def entry_mode(pop, imp_pc, rule):
    if pop >= rule["local_min_population"] and imp_pc < rule["local_max_import_per_capita_usd"]:
        return "현지생산·인수형", f"인구 {pop/1e6:,.0f}백만 명인데 1인당 과자 수입 {imp_pc:.1f}달러로 적음(인도형)"
    return "수출형", f"1인당 과자 수입 {imp_pc:.1f}달러로 이미 수입 과자를 사 먹는 시장"


def run(cfg_path):
    cfg = yaml.safe_load(open(cfg_path, encoding="utf-8"))
    top3 = [r["iso3"] for r in json.load(open(ROOT / cfg["ranking"]))["ranking"][:3]]
    panel = {c["iso3"]: c for c in json.load(open(ROOT / cfg["panel"]))["countries"]}
    n, fx, L = cfg["years_ahead"], cfg["krw_per_usd"], cfg["lotte_share_of_korea"]
    G = cfg.get("target_share_gain_pp", 0) / 100
    out = []
    for iso in top3:
        c = panel[iso]; r = c["raw"]
        mkt = math.exp(r["import_market_size"]); pop = math.exp(r["population_size"])
        kor = c["kor"]; share = kor / mkt
        mkt_n = mkt * (1 + r["import_market_cagr"] / 100) ** n
        trend_share = share + r["korea_share_change"] / 100 * n / 5
        inc = sorted([mkt_n * share - kor, mkt_n * trend_share - kor])
        mode, why = entry_mode(pop, mkt / pop, cfg["entry_rule"])
        eok = lambda usd: round(usd * fx / 1e8)
        out.append({
            "iso3": iso, "name": c["name"],
            "import_market_2024_eok": eok(mkt), "import_market_growth_pct": round(r["import_market_cagr"], 1),
            "korea_exports_2024_eok": eok(kor), "korea_share_pct": round(share * 100, 1),
            "korea_share_change_5y_pp": round(r["korea_share_change"], 1),
            "korea_increase_eok": [eok(inc[0]), eok(inc[1])],
            "lotte_opportunity_eok": [eok(inc[0] * L), eok(inc[1] * L)],
            "value_of_1pp_share_eok": eok(mkt_n * 0.01),
            "entry_target_eok": [eok(inc[0] * L + mkt_n * G), eok(inc[1] * L + mkt_n * G)],
            "entry_mode": mode, "entry_reason": why,
        })
    return cfg, out


def to_md(cfg, rows):
    n = cfg["years_ahead"]
    L = round(cfg["lotte_share_of_korea"] * 100)
    t = [f"# TOP3 비즈니스 임팩트 ({2024+n}년, 2024년 대비 연 매출 증가)\n",
         f"환율 {cfg['krw_per_usd']:,}원/달러, 롯데 몫 {L}%(제과 3사 해외 매출 중 롯데 비중, 2023).\n",
         "| 나라 | 진입 방식 | 진출 목표 매출(연) | 가만히 있어도 느는 몫(연) | 한국 과자 전체 증가(연) | 점유율 1%p 가치(연) | 과자 수입시장 2024 (성장률) | 한국산 비중 (5년 변화) |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        a, b = r["lotte_opportunity_eok"]; c, d = r["korea_increase_eok"]
        e1, e2 = r["entry_target_eok"]
        t.append(f"| {r['name']} | {r['entry_mode']} | {e1}~{e2}억 | {a}~{b}억 | {c}~{d}억 | {r['value_of_1pp_share_eok']}억 | "
                 f"{r['import_market_2024_eok']:,}억 ({r['import_market_growth_pct']}%/년) | "
                 f"{r['korea_share_pct']}% ({r['korea_share_change_5y_pp']:+}%p) |")
    t.append("\n진입 방식 근거:")
    for r in rows:
        t.append(f"- {r['name']}: {r['entry_mode']}. {r['entry_reason']}.")
    tot = [sum(r["entry_target_eok"][i] for r in rows) for i in (0, 1)]
    t.append(f"\n**3개국 진출 목표 합계: 연 {tot[0]}~{tot[1]}억** (점유율 +{cfg.get('target_share_gain_pp', 0)}%p 목표 + 가만히 있어도 느는 몫)")
    t.append("\n범위의 두 끝: 한국산 비중이 지금 그대로인 경우와, 지난 5년 변화 속도로 계속 움직이는 경우.")
    return "\n".join(t) + "\n"


if __name__ == "__main__":
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else ROOT / "config/impact/lotte_impact.yaml"
    cfg, rows = run(cfg_path)
    od = ROOT / "outputs/three_criteria"
    json.dump(rows, open(od / "business_impact.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = to_md(cfg, rows)
    open(od / "business_impact.md", "w", encoding="utf-8").write(md)
    print(md)
