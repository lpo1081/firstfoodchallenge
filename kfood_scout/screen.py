"""결과 화면: 3대 기준 결과 + 레드팀 판정 + 외부 교차 확인을 HTML 한 장으로. 2026-11-03.

읽는 것(전부 파일, API 호출 없음, 비용 0원):
  outputs/three_criteria/result.json      엔진 결과(순위, 기준 점수, 지표별 값·비중)
  outputs/agent/critic/<ISO3>.json        레드팀 카드(판정·진출 조건·반론·기사). 없으면 아래 대체
  outputs/agent/<category>/board.md       레드팀 장부(카드가 없을 때 반론·기사만 읽음)
  outputs/three_criteria/business_impact.json  롯데 기회 규모(원)·진입 방식(있을 때만)
  config/screen/screen.yaml               품목 선정 이유, 못 넣은 지표, 외부 교차 확인, 판정 대체값, 한글 국가명
쓰는 것: outputs/three_criteria/screen.html

실행: .venv/bin/python -m kfood_scout.screen   (scripts/three.sh 끝에서 자동 실행)
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import yaml

from .config import ROOT

CAT = "dry_confectionery"
G3 = ["성장성", "트렌드", "수출입"]
TEMPLATE = Path(__file__).with_name("screen_template.html")
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


def _cards(root: Path) -> dict:
    d = _src(root, "agent", "critic")
    out = {}
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        if len(p.stem) != 3:
            continue
        try:
            c = json.loads(p.read_text())
        except Exception:
            continue
        ev = lambda e: [{"t": f"{x.get('publisher') or x.get('title', '')} {x.get('date', '')}".strip(), "u": x.get("url", "")}
                        for x in (e or [])]
        out[p.stem] = {
            "verdict": c.get("verdict"), "conditions": c.get("conditions", []), "go_line": c.get("go_line", ""),
            "summary": c.get("summary", ""), "source": "레드팀 카드",
            "cons": [{"sev": o.get("severity", ""), "cat": o.get("category", ""), "t": o.get("claim", ""),
                      "cond": o.get("condition", ""), "src": ev(o.get("evidence"))} for o in c.get("objections", [])],
            "pros": [{"t": s.get("claim", ""), "src": ev(s.get("evidence"))} for s in c.get("support", [])]}
    return out


def _split_src(s: str):
    t, src = (s.rsplit(" — ", 1) + [""])[:2] if " — " in s else (s, "")
    return t.strip(), [{"t": a, "u": u} for a, u in LINK.findall(src)]


def parse_board(md: str) -> dict:
    """레드팀 장부(board.md)의 나라별 절에서 총평·반론·반박을 읽는다(카드가 없을 때만)."""
    red = {}
    for blk in re.split(r"\n### ", md)[1:]:
        head, _, body = blk.partition("\n")
        m = re.match(r"(.+?) \((\w{3})\)", head)
        if not m:
            continue
        body = body.split("\n## ")[0]
        main, _, pro = body.partition("반박(진출 지지 근거):")
        lines = [l for l in main.strip().split("\n") if l.strip()]
        cons = []
        for l in lines[1:]:
            mm = re.match(r"- \[(\S+?)·(.+?)\] (.+)", l)
            if mm:
                t, src = _split_src(mm.group(3))
                cons.append({"sev": mm.group(1), "cat": mm.group(2), "t": t, "cond": "", "src": src})
        pros = []
        for l in pro.strip().split("\n"):
            if l.startswith("- "):
                t, src = _split_src(l[2:])
                pros.append({"t": t, "src": src})
        red[m.group(2)] = {"summary": lines[0] if lines else "", "cons": cons, "pros": pros}
    return red


def _kind(status: list[str]) -> str:
    s = " ".join(status)
    if "기진출" in s:
        return "기진출"
    if "상위 5" in s:
        return "큰시장"
    if "사전 필터" in s:
        return "필터"
    return "바닥"


def build_data(res: dict, cfg: dict, cards: dict, board_red: dict, impact: list | None = None) -> dict:
    ko = cfg.get("names_ko", {})
    B = res.get("B") or 0
    cands, out, detail = [], [], {}
    for b in res["board"]:
        iso = b["iso3"]
        row = {"iso": iso, "ko": ko.get(iso, b["name"]), "kor": round(b["kor_exports_2024_usd"] / 1e6, 1),
               "rank_all": b.get("rank"), "score": b.get("score"), "g": b.get("criteria"),
               "gpool": b.get("criteria_rank_in_pool_pct"), "warn": b.get("warn", []), "why": b.get("reasons", [])}
        if b.get("detail"):
            detail[iso] = b["detail"]
        if b["status"]:
            out.append(dict(row, status=b["status"], kind=_kind(b["status"])))
        else:
            p = b.get("top3_stability_pct")
            cands.append(dict(row, p=p, hits=(round(p * B / 100) if p is not None and B else None)))
    order = {c: i for i, c in enumerate(res.get("order_iso3") or [])}
    cands.sort(key=lambda r: (order.get(r["iso"], 999), -(r["score"] or 0)))
    cnt = {}
    for r in out:
        cnt[r["kind"]] = cnt.get(r["kind"], 0) + 1

    fb = cfg.get("fallback_decisions", {})
    dec, red = {}, {}
    for c in cands[:3]:
        iso = c["iso"]
        if iso in cards:
            k = cards[iso]
            dec[iso] = {"verdict": k["verdict"], "how": k.get("go_line", ""), "conditions": k["conditions"], "source": "레드팀 카드"}
            red[iso] = k
        else:
            f = fb.get(iso, {})
            dec[iso] = {"verdict": f.get("verdict", "검토 전"), "how": f.get("how", ""), "conditions": f.get("conditions", []),
                        "source": "레드팀 장부를 사람이 정리"}
            if iso in board_red:
                red[iso] = board_red[iso]

    dev, sealed = res.get("dev", {}), res.get("sealed", {})
    pick = lambda d, k: (d.get(k) or {}).get("rank_corr")
    E, S, T = "앙상블(선택 모델)", "[기준선] 큰 시장 순", "[기준선] 직전 3년 증가 순"
    gi = {}
    for i in res["indicators"]:
        gi.setdefault(i["group"], []).append(i["name"])
    return {
        "meta": {"category": cfg.get("category_ko", ""), "hs": cfg.get("hs_label", ""), "why_cat": cfg.get("category_reason", ""),
                 "protocol": res.get("protocol"), "filter": res.get("filter"), "n_ind": len(res["indicators"]),
                 "generated": dt.date.today().isoformat(), "sources": cfg.get("data_sources", [])},
        "total": len(res["board"]), "cnt": cnt, "cands": cands, "out": out, "detail": detail,
        "big5": [ko.get(x, x) for x in (res.get("big5_iso3") or [])],
        "dec": dec, "red": red, "impact": {x["iso3"]: x for x in (impact or [])}, "impact_note": cfg.get("impact_note", ""), "gaps": cfg.get("gaps", []), "groups_ind": gi,
        "xc": cfg.get("crosscheck", {}), "evidence": cfg.get("evidence", {}),
        "crit_text": cfg.get("criteria_text", {}), "notes": cfg.get("indicator_notes", {}),
        "indicators": res["indicators"], "weights": res.get("weights", {}), "robust": res.get("robustness", {}),
        "agent_flow": cfg.get("agent_flow", []), "agent_note": cfg.get("agent_note", ""),
        "val": {"dev": {k: pick(dev, k) for k in (E, S, T)}, "n_dev": len(res.get("dev_rows", [])), "sealed": {k: pick(sealed, k) for k in (E, S, T)},
                "B": B, "gw": res.get("group_weights", {}), "windows": len(res.get("windows", {})),
                "n_all": res.get("n_scored") or len(res["board"])},
    }


def render(data: dict) -> str:
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.read_text().replace("__DATA__", js)


def _src(root: Path, *parts: str) -> Path:
    """실행 결과(outputs/, git 밖)가 있으면 그것을, 없으면 저장소의 스냅샷(results/)을 읽는다."""
    p = root.joinpath("outputs", *parts)
    return p if p.exists() else root.joinpath("results", *parts)


def main(root: Path = ROOT) -> Path:
    res = json.loads(_src(root, "three_criteria", "result.json").read_text())
    cfg = yaml.safe_load((root / "config" / "screen" / "screen.yaml").read_text())
    bp = _src(root, "agent", CAT, "board.md")
    board_red = parse_board(bp.read_text()) if bp.exists() else {}
    ip = _src(root, "three_criteria", "business_impact.json")   # scripts/business_impact.py 결과(있을 때만)
    impact = json.loads(ip.read_text()) if ip.exists() else []
    html = render(build_data(res, cfg, _cards(root), board_red, impact))
    out = root / "outputs" / "three_criteria" / "screen.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"[screen] {out}")
    return out


if __name__ == "__main__":
    main()
