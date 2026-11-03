"""API 비용 기록과 예산 상한.

Claude API 응답마다 토큰 사용량(usage)을 읽어 달러로 바꾸고 outputs/agent/costs.jsonl 에 한 줄씩 쌓는다.
에이전트는 Budget 을 넘기기 전에 스스로 멈춘다. 가격은 2026-10 기준 공시가(1백만 토큰당 USD).
확인: python -m kfood_scout.agent cost
"""
from __future__ import annotations

import datetime as dt
import json

from ..config import ROOT

# 모델별 (입력, 출력, 캐시 읽기, 캐시 쓰기) $/1M 토큰
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-8": (5.0, 25.0, 0.50, 6.25),
}
WEB_SEARCH_PER_1K = 10.0  # 웹 검색 1,000회당 $10 (웹 페이지 읽기는 토큰 값만)
LOG = ROOT / "outputs" / "agent" / "costs.jsonl"


def usd(model: str, usage) -> float:
    p = PRICES.get(model, PRICES["claude-opus-5-5"])
    g = lambda k: getattr(usage, k, None) or 0  # noqa: E731
    stu = getattr(usage, "server_tool_use", None)
    searches = (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
    return (g("input_tokens") * p[0] + g("output_tokens") * p[1] + g("cache_read_input_tokens") * p[2]
            + g("cache_creation_input_tokens") * p[3]) / 1e6 + searches * WEB_SEARCH_PER_1K / 1000


class Budget:
    """한 번의 실행(run)에서 쓸 수 있는 돈. record() 로 쌓고 left 로 남은 돈을 본다."""

    def __init__(self, limit_usd: float = 3.0, run: str | None = None, path=None):
        self.limit, self.spent, self.calls = limit_usd, 0.0, 0
        self.run = run or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = path or LOG

    @property
    def left(self) -> float:
        return self.limit - self.spent

    def exhausted(self, reserve: float = 0.0) -> bool:
        return self.spent + reserve >= self.limit

    def record(self, purpose: str, resp) -> float:
        model = getattr(resp, "model", "claude-opus-5-5")
        cost = usd(model, resp.usage)
        self.spent += cost
        self.calls += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        u = resp.usage
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "run": self.run, "purpose": purpose,
                                "model": model, "in": getattr(u, "input_tokens", 0), "out": getattr(u, "output_tokens", 0),
                                "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                                "usd": round(cost, 4), "run_total": round(self.spent, 4)}, ensure_ascii=False) + "\n")
        return cost


def summary(path=None) -> str:
    p = path or LOG
    if not p.exists():
        return "비용 기록 없음"
    rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    by_run, by_purpose = {}, {}
    for r in rows:
        by_run[r["run"]] = by_run.get(r["run"], 0) + r["usd"]
        k = r["purpose"].split(":")[0]
        by_purpose[k] = by_purpose.get(k, 0) + r["usd"]
    lines = [f"총 {len(rows)}회 호출, ${sum(by_run.values()):.2f}", "실행별:"]
    lines += [f"  {k}: ${v:.2f}" for k, v in by_run.items()]
    lines += ["용도별:"] + [f"  {k}: ${v:.2f}" for k, v in by_purpose.items()]
    return "\n".join(lines)
