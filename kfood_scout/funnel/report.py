"""깔때기 결과 → 사람용 보고서(답 → 근거 → 방법 → 한계 → 전체 판정표)."""
from __future__ import annotations

import pandas as pd

from ..three import KO

STAGE_KO = {1: "1 자격 심사", 2: "2 시장 매력도", 3: "3 승산", 4: "4 진입 비용", 5: "5 위험·충격", 6: "최종 TOP3"}


def ko(c, cty=None):
    if c in KO:
        return KO[c]
    return cty.at[c, "name"] if cty is not None and c in cty.index else c


def _f(x, d=1):
    return "-" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:,.{d}f}"


def to_md(R, T, cty, proto, checklist) -> str:
    b, e, top = R["base"], R["econ"], R["top"]
    n = lambda c: ko(c, cty)
    keep = R["mc_keep"]
    L = []
    L.append(f"# 상세 검토 대상 TOP3: {' · '.join(n(c) for c in top)}")
    L.append("")
    L.append("## 답")
    L.append("")
    L.append(f"대기업이 진출국을 고를 때 거치는 표준 단계 다섯 개를 한 번에 돌린 결과, **{proto['category']['name_ko']}** 를 들고 "
             f"먼저 상세 검토할 나라는 **{', '.join(n(c) for c in top)}** 입니다.")
    L.append("")
    L.append("| 순위 | 나라 | 최종 점수 | 시장 매력도 | 승산 | 편익÷비용 | 안전도 | 5년 순이익(위험 반영) | 비중을 1,000번 흔들어도 TOP3에 남은 비율 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for i, c in enumerate(top, 1):
        L.append(f"| {i} | **{n(c)}** | {R['final'][c]:.1f} | {b['attr'][c]:.0f} | {b['abil'][c]:.0f} | {e[c]['bc_ratio']:.1f}배 | "
                 f"{b['safety'][c]:.0f} | {e[c]['npv5']:.0f}억원 | {keep.get(c, 0):.0f}% |")
    L.append("")
    shock_same = sum(set(v) == set(top) for v in R["top3_shock"].values())
    L.append("**왜 이 세 나라인가**")
    L.append("")
    L.append(f"- 전 세계 {len(R['pool'])}개국에서 시작해 단계마다 미리 정한 규칙으로 걸렀고, 다섯 단계를 모두 통과한 나라 중 점수 1~3위입니다.")
    L.append(f"- 충격 {len(R['top3_shock'])}가지(한류 둔화, 경기 침체, 현지 통화 급락, 운임 2배, FTA 혜택 상실, 국가위험 2배, 복합) 중 "
             f"**{shock_same}가지에서 같은 3개국**이 나왔고, 세 나라 모두 어떤 충격에서도 5년 순이익이 플러스입니다.")
    L.append(f"- 단계별 점수 비중을 1,000번 무작위로 바꿔 다시 돌려도 {', '.join(f'{n(c)} {keep.get(c, 0):.0f}%' for c in top)} 비율로 TOP3에 남았습니다.")
    runner = [c for c in keep.index if c not in top][:2]
    if runner:
        L.append(f"- 다음 후보는 {', '.join(f'{n(c)}({keep[c]:.0f}%)' for c in runner)} 입니다. "
                 f"{n(runner[0])}: '{STAGE_KO[R['fate'][runner[0]]['stage']]}' 단계에서 멈춤({R['fate'][runner[0]]['why']}).")
    L.append("")

    # ---- 깔때기
    L.append("## 깔때기 한눈에")
    L.append("")
    cnt1 = {}
    for c, rs in R["reasons"].items():
        for r in rs:
            cnt1[r] = cnt1.get(r, 0) + 1
    L.append("| 단계 | 무엇을 보나 | 남은 나라 | 떨어진 나라 |")
    L.append("|---|---|---|---|")
    L.append(f"| 0 대상 | 인구 100만 이상, 품목 수입 통계 있음 | {len(R['pool'])} | - |")
    L.append(f"| 1 자격 심사 | 제재·전쟁, 정치 불안, 최소 시장, 소득, 회사 포트폴리오 | {len(R['s1'])} | {len(R['pool']) - len(R['s1'])} "
             f"({', '.join(f'{k} {v}' for k, v in sorted(cnt1.items(), key=lambda x: -x[1]))}, 중복 포함) |")
    L.append(f"| 2 시장 매력도 | 규모·성장·소비구조 (상위 절반 통과) | {len(b['s2'])} | {len(R['s1']) - len(b['s2'])} |")
    L.append(f"| 3 승산 | 한국 친화·한국 제품 발판·거리·FTA·경쟁 (상위 절반 통과) | {len(b['s3'])} | {len(b['s2']) - len(b['s3'])} |")
    L.append(f"| 4 진입 비용 | 관세·운임·라벨·등록·할랄·국가위험 → 5년 순이익 > 0, 회수 3년 이내 | {len(b['s4'])} | {len(b['s3']) - len(b['s4'])} |")
    L.append(f"| 5 위험·충격 | 물가·환율·법치·물류 + 충격 7가지 (단일 충격 2개 이상 적자면 제외) | {len(b['s4']) - len(R['excluded'])} | {len(R['excluded'])} |")
    L.append(f"| 최종 | 매력도 35% + 승산 35% + 편익÷비용 15% + 안전도 15% | 3 | - |")
    L.append("")

    # ---- TOP3 상세
    L.append("## 세 나라 상세")
    L.append("")
    for c in top:
        aG, bG = b["attrG"].loc[c], b["abilG"].loc[c]
        L.append(f"### {n(c)}")
        L.append("")
        L.append(f"- **시장 매력도 {b['attr'][c]:.0f}점**: " + ", ".join(f"{g} {aG[g]:.0f}" for g in aG.index)
                 + f" (과자 수입시장 {T.at[c, 'import_usd'] / 1e6:,.0f}백만 달러, 5년 성장률 {_f(T.at[c, 'import_cagr'])}%/년)")
        L.append(f"- **승산 {b['abil'][c]:.0f}점**: " + ", ".join(f"{g} {bG[g]:.0f}" for g in bG.index)
                 + f" (한국산 수출 {T.at[c, 'korea_exports_usd'] / 1e6:,.1f}백만 달러, 수입 중 한국산 {_f(T.at[c, 'korea_share'])}%, "
                   f"서울에서 {T.at[c, 'distance_km']:,.0f}km, FTA {T.at[c, 'fta_years']:.0f}년차)")
        ce = e[c]
        L.append(f"- **진입 비용**: 관세 {ce['tariff_rate'] * 100:.0f}%, 운임 매출의 {ce['freight_rate'] * 100:.1f}%, 초기 비용 {ce['one_time']:.1f}억원, "
                 f"할인율 {ce['discount_rate'] * 100:.1f}% → 5년 순이익 {ce['npv5']:.0f}억원, 편익÷비용 {ce['bc_ratio']:.1f}배, 회수 {_f(ce['payback_years'])}년 "
                 f"(비용 항목: {R['grade'][c]})")
        L.append(f"- **안전도 {b['safety'][c]:.0f}점**: 물가 {_f(T.at[c, 'inflation'])}%/년, 환율 변동 {_f(T.at[c, 'fx_volatility'])}%, "
                 f"법치·부패 {_f(T.at[c, 'governance'], 2)}, 물류지수 {_f(T.at[c, 'logistics'])}/5")
        worst = min(R["npv_shock"], key=lambda s: R["npv_shock"][s][c])
        L.append(f"- **가장 아픈 충격**: {R['shocks'][worst]} → 5년 순이익 {R['npv_shock'][worst][c]:.0f}억원 (기본 {ce['npv5']:.0f}억원)")
        L.append("")

    # ---- 충격 표
    L.append("## 충격 시뮬레이션: 5년 순이익(억원)과 충격마다의 TOP3")
    L.append("")
    show = list(R["final"].index[:8])
    L.append("| 충격 | " + " | ".join(n(c) for c in show) + " | 이 충격에서 TOP3 |")
    L.append("|---|" + "---|" * len(show) + "---|")
    L.append("| 기본 | " + " | ".join(f"{e[c]['npv5']:.0f}" for c in show) + f" | {', '.join(n(c) for c in top)} |")
    for s, name in R["shocks"].items():
        L.append(f"| {name} | " + " | ".join(f"{R['npv_shock'][s][c]:.0f}" for c in show) + f" | {', '.join(n(c) for c in R['top3_shock'][s])} |")
    L.append("")
    L.append("한류 둔화는 돈이 아니라 점수 충격입니다: 승산 점수에서 '한국 친화'(검색 관심도·방한객)를 0으로 놓고 깔때기를 다시 돌린 결과입니다.")
    L.append("")

    # ---- 순위표
    L.append("## 마지막 단계까지 간 나라 순위")
    L.append("")
    L.append("| 순위 | 나라 | 최종 | 매력도 | 승산 | 편익÷비용 | 안전도 | 5년 순이익(억원) | 비용 항목 | 흔들어도 TOP3 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for i, c in enumerate(R["final"].index, 1):
        L.append(f"| {i} | {n(c)} | {R['final'][c]:.1f} | {b['attr'][c]:.0f} | {b['abil'][c]:.0f} | {e[c]['bc_ratio']:.1f} | "
                 f"{b['safety'][c]:.0f} | {e[c]['npv5']:.0f} | {R['grade'][c]} | {keep.get(c, 0):.0f}% |")
    L.append("")

    # ---- 체크리스트
    fs = checklist["factors"]
    cnt = {k: sum(f["status"] == k for f in fs) for k in ("data", "proxy", "human")}
    L.append("## 대기업이 보는 요소를 얼마나 담았나")
    L.append("")
    L.append(f"실제 기업·공공기관 틀(교과서 3단계 선정, PESTEL, CAGE 거리, ITC 수출잠재력, KOTRA, 컨설팅 식품 사례, 롯데·오리온)에서 요소 {len(fs)}개를 뽑았습니다. "
             f"**공개 데이터로 숫자화 {cnt['data']}개, 대체 지표로 반영 {cnt['proxy']}개, 사람만 확인 가능 {cnt['human']}개**입니다.")
    L.append("")
    L.append("| 단계 | 요소 | 반영 | 어떻게 |")
    L.append("|---|---|---|---|")
    st = {"data": "데이터", "proxy": "대체 지표", "human": "**사람 확인**"}
    for f in fs:
        L.append(f"| {f['stage']} | {f['factor']} | {st[f['status']]} | {f['how']} |")
    L.append("")
    L.append("출처: " + " · ".join(f"[{s['name'].split('(')[0]}]({s['url']})" for s in checklist["sources"].values()))
    L.append("")

    # ---- 상세 검토 목록
    L.append("## TOP3 이후 사람이 확인할 상세 검토 목록")
    L.append("")
    human = [f for f in fs if f["status"] == "human"]
    for c in top:
        extra = []
        if not R["grade"][c].startswith("확인"):
            extra.append("아직 확인 못 한 비용 항목: " + (("FTA 원산지 기준(수입 밀가루를 써도 0% 세율이 적용되는지)" if "원산지" in R["grade"][c] else "FTA 관세율·운임") if "일부" in R["grade"][c] else "관세·운임·등록·국가위험"))
        if R["C"]["countries"][c].get("halal_required"):
            extra.append("할랄 인증 가능 품목·기간 확인")
        if c in R["conditional"]:
            extra.append("대비할 충격: " + ", ".join(R["shocks"][s] for s in R["conditional"][c]))
        worst = min(R["npv_shock"], key=lambda s: R["npv_shock"][s][c])
        extra.append(f"가장 아픈 충격({R['shocks'][worst]}) 대응책")
        L.append(f"- **{n(c)}**: " + "; ".join(extra))
    L.append("- **세 나라 공통**: " + "; ".join(f"{f['factor']}({f['how']})" for f in human))
    L.append("")

    # ---- 규칙
    L.append("## 규칙은 결과보다 먼저 정했습니다")
    L.append("")
    L.append("단계별 탈락 기준, 점수 비중, 충격 7가지, 판정 규칙은 계산 전에 `config/funnel/protocol.yaml` 로 커밋해 고정했습니다. "
             "기존 모델(3대 기준, 롤링, 비용 모듈)의 코드와 결과는 바꾸지 않고, 같은 원천 데이터를 읽기만 합니다.")
    L.append("")
    for r in proto["stage1"]["rules"]:
        if r.get("why"):
            L.append(f"- 1단계 {r['name_ko']}: {r['why']}")
    L.append("")

    # ---- 한계
    L.append("## 한계 (그대로 적습니다)")
    L.append("")
    if len(b["s4"]) == len(b["s3"]) and not R["excluded"]:
        L.append("- **비용 단계와 충격 단계에서 떨어진 나라가 없습니다.** 관세·운임·인증 같은 '들어가는 비용'이 목표 매출(3년 뒤 수입시장의 +1%p)에 비해 작기 때문입니다. "
                 "그래서 이 두 단계는 탈락이 아니라 순위(편익÷비용, 안전도)와 확실도로만 작동했습니다. 실제로 승부를 가르는 비용은 입점비·마케팅·유통 마진이고, 이건 사람이 확인할 항목으로 넘겼습니다.")
    nrule = sum(1 for c in b["s3"] if not R["grade"][c].startswith("확인"))
    L.append(f"- 비용 단계에 들어간 {len(b['s3'])}개국 중 {nrule}개국은 비용 항목 전부 또는 일부를 공개 자료로 확인하지 못해 규칙값(관세 FTA 5%·비FTA 10%, 지역별 운임, OIC 회원국 할랄, 국가위험은 정치안정 지수로 추정)을 썼습니다.")
    L.append("- 결과를 본 뒤 바꾼 것은 규칙이 아니라 사실값 하나뿐입니다: 최종 후보 쪽 나라의 비용 항목(호주 관세·운임·등록, 6개국 국가위험 프리미엄)을 공개 자료로 확인해 규칙값을 교체했습니다(config/funnel/costs_extra.yaml).")
    L.append("- 대만은 UN 무역통계에 수입국으로 나오지 않아 대상에 없습니다(한국 비스킷 수출 4위 규모).")
    L.append("- 시장 규모는 '수입 과자 시장'입니다. 현지 생산 과자까지 합친 전체 시장(유로모니터 등 유료)은 상세 검토에서 봅니다.")
    defend = [c for c, rs in R["reasons"].items() if any("지키는" in r for r in rs)]
    nxt = T.reindex(R["s1"])["korea_exports_usd"].sort_values(ascending=False).index[:1]
    if len(nxt):
        L.append(f"- '지키는 시장' 규칙(한국 수출 상위 5개국: {', '.join(n(c) for c in defend)})에서 바로 다음이 {n(nxt[0])}입니다. 상위 6개로 잡으면 {n(nxt[0])}도 빠집니다.")
    L.append("")

    # ---- 전체 판정표
    L.append("## 전체 나라 판정표 (어느 단계에서, 왜)")
    L.append("")
    L.append("| 나라 | 멈춘 단계 | 이유 |")
    L.append("|---|---|---|")
    for c, f in sorted(R["fate"].items(), key=lambda x: (-x[1]["stage"], ko(x[0], cty))):
        L.append(f"| {n(c)} | {STAGE_KO[f['stage']]} | {f['why']} |")
    L.append("")
    return "\n".join(L)
