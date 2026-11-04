"""최종 화면(통합 깔때기 결과): 138개국 → 5단계 → 3개국을 HTML 한 장으로. 2026-11-03.

읽는 것(전부 파일, API 호출 없음, 비용 0원):
  outputs/funnel/<품목>/result.json      깔때기 결과(없으면 results/funnel/<품목>/result.json 스냅샷)
  config/funnel/protocol.yaml            단계별 규칙·지표 비중(결과 계산 전에 고정한 것)
  config/funnel/checklist.yaml           대기업이 보는 요소와 반영 방식
  config/screen/funnel_screen.yaml       나라별 진출 조건, 지표 표시 이름, 단계 설명
  config/screen/screen.yaml              현장 근거, 'AI 에이전트가 한 일' 기록, 데이터 출처, 품목 선정 이유
  outputs/agent/<품목>/board.md          레드팀 장부(있으면 나라별 반론·기사)
쓰는 것: outputs/funnel/<품목>/screen.html

실행: .venv/bin/python -m kfood_scout.screen_funnel [--category biscuits]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path

import yaml

from .config import ROOT
from .screen import parse_board

TEMPLATE = Path(__file__).with_name("screen_funnel_template.html")


def _y(p: Path) -> dict:
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def _result_path(root: Path, cat: str) -> Path:
    for d in ("outputs", "results"):
        p = root / d / "funnel" / cat / "result.json"
        if p.exists():
            return p
    raise FileNotFoundError(f"funnel/{cat}/result.json 이 없습니다. 먼저 sh scripts/funnel.sh 를 실행하세요.")


def build_data(res: dict, proto: dict, checklist: dict, fcfg: dict, scfg: dict, board_red: dict) -> dict:
    ko = dict(scfg.get("names_ko", {}))
    name = lambda c: ko.get(c) or (res["fate"].get(c) or {}).get("name", c)
    final = res["final"]
    order = sorted(final, key=lambda c: -final[c])
    top = res["top3"]
    keep = set(order) | set(res.get("mc_top3_pct", {}))
    # 1단계 탈락 이유(중복 포함)
    s1 = Counter()
    for f in res["fate"].values():
        if f["stage"] == 1:
            for w in f["why"].split(" · "):
                s1[w] += 1
    fate = {c: {"stage": f["stage"], "why": f["why"], "ko": name(c)} for c, f in res["fate"].items()}
    shocks_same = sum(1 for v in res["shock_top3"].values() if sorted(v) == sorted(top))
    fac = checklist.get("factors", [])
    st = Counter(f.get("status") for f in fac)
    ev = dict(scfg.get("evidence", {}))
    ev.update(fcfg.get("evidence", {}))
    red = {c: board_red[c] for c in top if c in board_red}
    return {
        "meta": {"title": fcfg.get("title", ""), "subtitle": fcfg.get("subtitle", ""), "category": res["category"]["name_ko"],
                 "hs": "HS " + "·".join(res["category"]["hs_codes"]), "as_of": proto.get("as_of"),
                 "protocol": res.get("protocol"), "frozen": str(proto.get("frozen") or ""), "why_cat": scfg.get("category_reason", ""),
                 "generated": dt.date.today().isoformat(), "sources": scfg.get("data_sources", [])},
        "top": top, "order": order, "ko": {c: name(c) for c in res["fate"]},
        "funnel": res["funnel"], "s1_why": s1.most_common(), "fate": fate,
        "final": final, "mc": {c: v for c, v in res.get("mc_top3_pct", {}).items() if v > 0},
        "mc_same3": res.get("mc_same3_pct"), "shocks": res["shocks"], "shock_top3": res["shock_top3"], "shocks_same": shocks_same,
        "shock_npv": {k: {c: v.get(c) for c in order} for k, v in res["shock_npv"].items()},
        "scores": {c: res["scores"][c] for c in res["scores"] if c in keep},
        "econ": {c: res["economics"][c] for c in order if c in res["economics"]},
        "ind": {c: res["indicators"][c] for c in order},
        "stages": fcfg.get("stages", []), "proto": {k: proto.get(k) for k in ("stage1", "stage2", "stage3", "stage4", "stage5")},
        "ind_spec": fcfg.get("indicators", {}),
        "checklist": {"n": len(fac), "data": st.get("data", 0), "proxy": st.get("proxy", 0), "human": st.get("human", 0),
                      "human_items": [f for f in fac if f.get("status") == "human"],
                      "sources": [v.get("name") for v in (checklist.get("sources") or {}).values()]},
        "dec": fcfg.get("decisions", {}), "frameworks": fcfg.get("frameworks", ""), "cross": fcfg.get("cross_check"), "evidence": ev, "red": red,
        "agent_flow": scfg.get("agent_flow", []), "agent_note": scfg.get("agent_note", ""),
    }


def render(data: dict) -> str:
    js = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    return TEMPLATE.read_text().replace("__DATA__", js)


def main(root: Path = ROOT, cat: str = "biscuits") -> Path:
    rp = _result_path(root, cat)
    res = json.loads(rp.read_text())
    proto = _y(root / "config" / "funnel" / "protocol.yaml")
    checklist = _y(root / "config" / "funnel" / "checklist.yaml")
    fcfg = _y(root / "config" / "screen" / "funnel_screen.yaml")
    scfg = _y(root / "config" / "screen" / "screen.yaml")
    board_red = {}
    for c in (cat, "dry_confectionery"):
        bp = root / "outputs" / "agent" / c / "board.md"
        if bp.exists():
            board_red = parse_board(bp.read_text())
            break
    html = render(build_data(res, proto, checklist, fcfg, scfg, board_red))
    out = root / "outputs" / "funnel" / cat / "screen.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"[screen] {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default="biscuits")
    main(cat=ap.parse_args().category)
