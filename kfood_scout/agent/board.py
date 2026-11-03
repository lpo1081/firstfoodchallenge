"""가설 장부: AI 가 낸 가설 → 통계 검증 결과 → 레드팀 반론 → 판정을 한 장(board.md)으로 모은다. 비용 0.

python -m kfood_scout.agent board
"""
from __future__ import annotations

from . import critic as cr
from . import loop

LABEL = {"accepted": "채택", "weak": "보류", "rejected": "기각", "data_needed": "데이터 필요",
         "scout_gave_up": "데이터 못 찾음", "scout_budget": "예산으로 탐색 중단", "scout_steps": "탐색 횟수 초과",
         "scout_refusal": "탐색 거절", "scout_registered": "데이터 찾아 등록(검증 대기)"}
SKIP = {"auto", "adopt"}


def _who(h: str, by: str) -> str:
    if "critic_" in h:
        return "레드팀 반론→AI"
    if by.startswith("llm") or h.startswith("auto_"):
        return "AI"
    return "사람"


def _latest(category: str) -> dict[str, dict]:
    out = {}
    for r in loop.ledger(category):
        if r["hypothesis"] in SKIP:
            continue
        prev = out.get(r["hypothesis"])
        # 검증 판정(accepted/weak/rejected)이 있으면 탐색 기록보다 우선
        if prev and prev["status"] in ("accepted", "weak", "rejected") and r["status"].startswith("scout_"):
            continue
        out[r["hypothesis"]] = r
    return out


def _cut(s: str, n: int = 70) -> str:
    s = (s or "").replace("|", "/").replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


def build(category: str = "dry_confectionery") -> str:
    hyps = _latest(category)
    cards = cr.load_cards()
    cnt = {}
    for r in hyps.values():
        k = LABEL.get(r["status"], r["status"])
        cnt[k] = cnt.get(k, 0) + 1
    ai = sum(1 for h, r in hyps.items() if _who(h, r.get("proposed_by", "")) != "사람")
    md = [f"# 가설 장부 ({category})", "",
          "AI 가 가설을 내고, 통계 엔진이 과거 데이터(표본 밖)로 시험하고, 레드팀 AI 가 기사로 결론을 공격한 기록입니다.", "",
          "## 요약", "",
          f"- 가설 {len(hyps)}개 중 AI 제안 {ai}개. 판정: " + ", ".join(f"{k} {v}" for k, v in cnt.items()),
          ]
    if cards:
        md.append("- 레드팀 판정: " + ", ".join(f"{c['name_ko']} {c['verdict']}" for c in cards))
        dropped = sum(len(c.get("dropped", [])) for c in cards)
        total = dropped + sum(len(c["objections"]) for c in cards)
        md.append(f"- 레드팀 반론 {total}개 중 {dropped}개는 근거(검색된 기사)가 없거나 오래돼 버림")
    md += ["", "## 1. 가설과 통계 검증", "",
           "| 가설 | 누가 | 내용 | 판정 | 표본 밖 개선 | 우위 확률 |", "|---|---|---|---|---|---|"]
    for h, r in hyps.items():
        o = r.get("oos") or {}
        d = f"{o['mean_delta']:+.3f}" if o.get("mean_delta") is not None else "-"
        p = f"{o['p_better'] * 100:.0f}%" if o.get("p_better") is not None else "-"
        md.append(f"| {h} | {_who(h, r.get('proposed_by', ''))} | {_cut(r.get('statement', ''))} | "
                  f"{LABEL.get(r['status'], r['status'])} | {d} | {p} |")
    md += ["", "채택 기준: 표본 밖(검증에 안 쓴 기간) 순위상관이 기존 모델보다 오르고, 우위 확률이 충분히 높을 때. "
           "자세한 근거는 report.md.", ""]
    if cards:
        md += ["## 2. 레드팀: 후보국을 뽑으면 안 되는 이유", "",
               "| 순위 | 나라 | 판정 | 치명 | 중간 | 낮음 | 가장 센 반론 |", "|---|---|---|---|---|---|---|"]
        for c in cards:
            top = sorted(c["objections"], key=lambda o: -cr.SEV.index(o["severity"]))
            md.append(f"| {c.get('rank', '')} | {c['name_ko']} | **{c['verdict']}** | {c['counts']['치명']} | "
                      f"{c['counts']['중간']} | {c['counts']['낮음']} | {_cut(top[0]['claim']) if top else '-'} |")
        md += ["", "판정 규칙(코드가 적용): 치명 반론 1개 이상 → 배제 권고, 중간 2개 이상 → 주의, 그 외 유지. "
               "치명은 서로 다른 출처 2곳 이상일 때만 인정.", ""]
        for c in cards:
            md += [f"### {c['name_ko']} ({c['iso3']}) — {c['verdict']}", "", c.get("summary", ""), ""]
            for o in sorted(c["objections"], key=lambda o: -cr.SEV.index(o["severity"])):
                links = ", ".join(f"[{_cut(e.get('publisher') or e['title'], 30)} {e['date']}]({e['url']})" for e in o["evidence"])
                note = f" ({o['note']})" if o.get("note") else ""
                md.append(f"- [{o['severity']}·{o['category']}] {o['claim']}{note} — {links}")
            if c.get("support"):
                md += ["", "반박(진출 지지 근거):"]
                for s in c["support"]:
                    md.append(f"- {s['claim']} — " + ", ".join(f"[{_cut(e.get('publisher') or e['title'], 30)}]({e['url']})"
                                                             for e in s["evidence"]))
            if c.get("dropped"):
                md += ["", f"근거 부족으로 버린 반론 {len(c['dropped'])}개: " +
                       "; ".join(_cut(d["claim"], 40) for d in c["dropped"])]
            md.append("")
        seeds = cr.load_seeds(k=100)
        if seeds:
            md += ["## 3. 반론에서 나온 다음 가설 후보", "",
                   "숫자로 측정할 수 있어 보이는 반론입니다. `agent auto` 를 돌리면 가설 담당 AI 가 이를 받아 지표 가설로 바꾸고 "
                   "통계 엔진이 검증합니다(장부 1번 표에 '레드팀 반론→AI' 로 기록).", "",
                   "| 나라 | 분야 | 반론 | 지표 아이디어 |", "|---|---|---|---|"]
            for s in seeds:
                md.append(f"| {s['iso3']} | {s['category']} | {_cut(s['claim'], 50)} | {_cut(s['indicator_idea'], 60)} |")
            md.append("")
    text = "\n".join(md)
    (loop.out_dir(category) / "board.md").write_text(text, encoding="utf-8")
    return text
