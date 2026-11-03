"""결과를 읽는 사람 기준 보고서로 (답 → 근거 → 비용 항목 → 민감도)."""

NAMES = {"PHL": "필리핀", "MYS": "말레이시아", "SGP": "싱가포르", "ARE": "UAE", "GBR": "영국"}


def _n(x, d=0):
    return f"{x:,.{d}f}"


def _row(i, r):
    pb = "첫해" if r["payback_years"] is not None and r["payback_years"] < 1 else (
        f"{r['payback_years']:.1f}년" if r["payback_years"] is not None else "5년 초과")
    return (f"| {i} | {r['name']} | {_n(r['revenue_target'])}억 | {r['tariff_rate']*100:.0f}% | "
            f"{r['freight_rate']*100:.1f}% | {_n(r['one_time'],1)}억 | {r['discount_rate']*100:.1f}% | "
            f"**{_n(r['npv5'])}억** | {r['npv5']/r['revenue_target']*100:.0f}% | {r['bc_ratio']:.2f} | {pb} |")


HEAD = ["| 순위 | 나라 | 연 목표 매출 | 관세 | 운임 | 초기 진입비 | 할인율(위험 포함) | 5년 순이익(현재가치) | 연매출 대비 | 편익÷비용 | 회수 |",
        "|---|---|---|---|---|---|---|---|---|---|---|"]


def to_md(P, C, res, sens, ref=()):
    top = res[0]
    old = "필리핀 → 싱가포르 → 말레이시아 (매출 기회 순)"
    new = " → ".join(r["name"] for r in res)
    L = ["# 진출 비용까지 따진 우선순위\n",
         f"**답: 1순위는 {top['name']}.** 진출 비용과 국가위험을 빼고 남는 5년 순이익이 "
         f"{_n(top['npv5'])}억으로 가장 큽니다. 순서는 **{new}**입니다 (비용 반영 전: {old}).\n",
         f"조건 {sens['n']}가지를 하나씩 바꿔 다시 계산해도 1순위가 {NAMES[sens['base_first']]}인 경우가 "
         f"{sens['first_kept']}가지, 세 나라 순서가 그대로인 경우가 {sens['top3_order_kept']}가지입니다.\n",
         "## 나라별 결과 (위험 반영 5년 순이익 순)\n"] + HEAD
    L += [_row(i, r) for i, r in enumerate(res, 1)]
    L += ["\n- 연 목표 매출: 3년 뒤 수입시장 점유율 +1%p + 가만히 있어도 느는 롯데 몫(비즈니스 임팩트와 같은 공식, 범위의 가운데).",
          f"- 이익 = 매출 x 매출총이익률 {P['gross_margin']*100:.0f}% - 관세(롯데 흡수) - 보험·통관 1% - 첫 2년 판촉 {P['launch_promo_rate']*100:.0f}% - 매년 고정비. 운임은 수입액(CIF)에서 빼서 롯데 매출로 환산.",
          "- 매출은 3년에 걸쳐 목표 도달(33%→67%→100%), 등록·인증 준비 기간만큼 첫해 매출이 줄어듭니다.",
          f"- 할인율 = 기본 {P['base_discount_rate']*100:.0f}% + 나라별 국가위험 프리미엄(Damodaran). 필리핀의 정치·환율 위험은 여기서 반영됩니다.",
          "- 편익÷비용 = 5년 매출총이익 ÷ 5년 비용(관세·보험통관·판촉·인증·등록·고정비), 둘 다 현재가치.",
          "- 초기 진입비(라벨·등록·할랄)는 나라마다 1억 안팎이라 첫해에 회수됩니다. 순위를 가르는 것은 진입비가 아니라 "
          "매년 드는 비용과 위험(국가위험 할인, 할랄 품목 제한)입니다.\n",
          "## 비용 항목과 출처\n",
          "| 나라 | 한국산 관세 (근거) | 운임 (KCCI 항로) | 표시·등록 | 할랄 | 준비 기간 | 국가위험 |",
          "|---|---|---|---|---|---|---|"]
    for iso in list(P["candidates"]) + list(P.get("reference") or []):
        cc = C["countries"][iso]
        if cc["tariff_korea"] is None:
            tr = f"MFN {cc['tariff_mfn']*100:.0f}%, 한국산 세율 미확인 → 규칙 min(MFN,5%)"
        elif cc["tariff_korea"] == cc["tariff_mfn"] and cc["tariff_mfn"] > 0:
            tr = f"{cc['tariff_korea']*100:.0f}% (FTA 원산지 미충족: 수입 밀가루)"
        elif cc["tariff_mfn"] > 0:
            tr = f"0% (FTA, MFN은 {cc['tariff_mfn']*100:.0f}%)"
        else:
            tr = "0% (관세 없음)"
        lab = "현지어 추가" if cc["extra_language"] else "영어"
        reg = "제품등록" if cc["registration_per_sku"] else "등록 없음"
        L.append(f"| {cc['name']} | {tr} | {cc['kcci_route']:,}p | {lab}, {reg} | "
                 f"{'필요(' + str(cc['halal_one_time']) + '억)' if cc['halal_required'] else '불필요'} | "
                 f"{cc['prep_months']}개월 | {cc['crp']*100:.2f}% |")
    L += ["\n출처: 관세 한-아세안 FTA 필리핀 양허표(asean.org), treayo.com(말레이시아 1905.31.20 AKFTA·RCEP 0%, MFN), "
          "한-영 FTA 원산지 헤럴드경제 2025-12-15, 한-UAE CEPA 2026-05-01 발효(Thomson Reuters), "
          "운임 한국해양진흥공사 KCCI 2026-10-26 주간(파이낸셜뉴스), 국가위험 Damodaran ctryprem, "
          "할랄 JAKIM 수수료(Halal Times), 필리핀 FDA CPR 처리 20영업일(ChemLinked). "
          "숫자별 출처와 확인 등급(확인/규칙/추정)은 config/entry_cost/costs.yaml.\n",
          "## 조건을 바꿔도 같은가\n",
          "| 바꾼 조건 | 1순위 | 순서 |", "|---|---|---|"]
    for c in sens["cases"]:
        L.append(f"| {c['change']} | {NAMES[c['first']]} | {' → '.join(NAMES[x] for x in c['order'])} |")
    if ref:
        L += ["\n## 참고: 영국·UAE (순위 밖)\n",
              "같은 공식으로 계산하면 숫자는 크지만 순위에 넣지 않았습니다. '+1%p 목표'가 큰 시장일수록 커지는 공식이라, "
              "영국에선 지금 한국산 비중(0.06%)의 17배를 팔아야 하는 비현실적 목표가 됩니다. "
              "비용 쪽에서 보이는 사실만 적습니다: 영국은 한-영 FTA가 있어도 수입 밀가루로 만든 과자는 원산지를 못 맞춰 관세 8%, "
              "UAE는 중동 운임이 동남아의 5배(매출의 약 18%)에 할랄·아랍어 표시가 필요합니다.\n"] + HEAD
        L += [_row("-", r) for r in ref]
        L.append("\n(이 두 나라를 순위에서 뺀 것은 결과를 본 뒤 바꾼 유일한 규칙입니다. 기록: config/entry_cost/protocol.yaml)")
    L.append("\n계산 규칙은 결과를 보기 전에 config/entry_cost/protocol.yaml 로 커밋해 고정했습니다.")
    return "\n".join(L) + "\n"
