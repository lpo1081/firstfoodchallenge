"""에이전트 CLI.

python -m kfood_scout.agent test   --hyp kculture            # 가설 하나 검증(데이터 없으면 수집)
python -m kfood_scout.agent loop   --rounds 2 --n 3           # LLM 가설 제안 → 검증 → 기록 반복
python -m kfood_scout.agent adopt                             # 채택 지표로 새 기준(k_export_agent.yaml) 생성
python -m kfood_scout.agent sealed                            # 봉인 구간(2021→24)에서 기존 vs 에이전트 기준 성적(비용 0)
python -m kfood_scout.agent report                            # 판정 기록 요약(outputs/agent/<category>/report.md)
python -m kfood_scout.agent auto   --budget 1.0               # 자율 실행: 가설→데이터 탐색→검증, 정체·예산 소진 시 스스로 종료
python -m kfood_scout.agent scout  --hyp auto_xxx             # 그 가설에 없는 데이터만 웹에서 찾아 등록
python -m kfood_scout.agent cost                              # API 비용 기록 요약(outputs/agent/costs.jsonl)
python -m kfood_scout.agent list                              # 가설 목록과 외부 데이터 준비 상태
python -m kfood_scout.agent critic --budget 1.0               # 레드팀: 후보국별 기사 검색 → 반론 카드(본 나라는 30일 무료 재사용)
python -m kfood_scout.agent critic --ranking 순위.csv --top 6  # 다른 순위 파일(iso3 열)의 상위 6개국을 공격
python -m kfood_scout.agent decide --budget 0.3              # 옛 반론 카드에 진출 조건 채우고 진출/조건부 진출/배제 재판정(검색 없음)
python -m kfood_scout.agent board                             # 가설 장부: 가설·검증·반론·판정 한 장(비용 0)
"""
import argparse
import json

from ..sources import external
from . import board, cost, critic, loop
from . import scout as sc


def main():
    ap = argparse.ArgumentParser(prog="kfood_scout.agent")
    ap.add_argument("cmd", choices=["test", "loop", "auto", "scout", "adopt", "sealed", "report", "cost", "list", "critic", "decide", "board"])
    ap.add_argument("--hyp")
    ap.add_argument("--category", default="dry_confectionery")
    ap.add_argument("--criterion", default="k_export")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--budget", type=float, default=1.0, help="이번 실행에서 쓸 API 비용 상한(USD)")
    ap.add_argument("--max-rounds", type=int, default=6)
    ap.add_argument("--patience", type=int, default=2, help="채택 없는 라운드가 이만큼 이어지면 종료")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--target-kind", choices=["abs", "log"], help="정답: abs=수출 증가액(기본), log=증가율")
    ap.add_argument("--ranking", help="critic: 후보 순위 파일(json/csv, iso3)")
    ap.add_argument("--countries", help="critic: ISO3 쉼표 목록(예: PHL,IDN,SGP)")
    ap.add_argument("--top", type=int, help="critic: 상위 몇 개국만")
    ap.add_argument("--refresh", action="store_true", help="critic: 캐시 무시하고 다시 검색(비용 발생)")
    ap.add_argument("--fast", action="store_true", help="탐색 수를 줄여 빠르게(n_fit=3000, B=200)")
    a = ap.parse_args()
    kw = {"n_fit": 3000, "B": 200} if a.fast else {}
    if a.target_kind:
        kw["target_kind"] = a.target_kind
    fetch = not a.no_fetch
    if a.cmd == "test":
        loop.test(a.hyp, a.category, a.criterion, fetch, **kw)
    elif a.cmd == "loop":
        loop.loop(a.category, a.criterion, a.rounds, a.n, fetch, **kw)
    elif a.cmd == "auto":
        s = loop.auto(a.category, a.criterion, a.max_rounds, a.n, a.patience, a.budget, fetch, **kw)
        print(json.dumps({k: s[k] for k in ("stop", "spent_usd", "api_calls")}, ensure_ascii=False))
    elif a.cmd == "scout":
        h = loop.load_hypotheses()[a.hyp]
        names = {c["series"] for c in external.catalog()}
        b = cost.Budget(a.budget)
        for i in h["indicators"]:
            if i["source"] == "external" and i["series"] not in names:
                r = sc.scout(i["series"], h.get("new_source_needed", ""), h, loop.YEARS, b)
                print(i["series"], r["status"], r.get("reason", ""))
        print(f"비용 ${b.spent:.2f}")
    elif a.cmd == "critic":
        s = critic.run(a.ranking, a.countries, a.top, a.budget, a.refresh)
        print(json.dumps(s, ensure_ascii=False))
        board.build(a.category)
        print(f"장부: outputs/agent/{a.category}/board.md")
    elif a.cmd == "decide":
        print(json.dumps(critic.backfill(a.budget), ensure_ascii=False))
        board.build(a.category)
        print(f"장부: outputs/agent/{a.category}/board.md")
    elif a.cmd == "board":
        print(board.build(a.category))
    elif a.cmd == "cost":
        print(cost.summary())
    elif a.cmd == "adopt":
        loop.adopt(a.category, a.criterion, fetch=fetch, **kw)
    elif a.cmd == "sealed":
        loop.sealed(a.category, a.criterion, fetch=fetch, **kw)
    elif a.cmd == "report":
        print(loop.report(a.category))
    else:
        for k, h in loop.load_hypotheses().items():
            print(k, "-", h.get("statement", "")[:80])
        print(json.dumps(external.catalog(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
