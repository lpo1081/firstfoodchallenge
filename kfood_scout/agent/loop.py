"""에이전트 루프: 가설 → 데이터 확보 → 검증 → 채택/기각 → 근거 기록 → (채택분으로) 모델 갱신.

- 가설은 config/hypotheses/*.yaml (사람이 쓴 것 + LLM이 낸 auto_*.yaml). 파일 하나 = 가설 하나.
- 모든 판정은 outputs/agent/<category>/ledger.jsonl 에 한 줄씩 쌓이고, 다음 제안의 입력이 된다.
- adopt: 채택된 지표를 기준 모델에 더하고, 가중치가 거의 0인 지표는 빼서 새 기준 파일(k_export_agent.yaml)을 만든다.
  기존 k_export.yaml 은 덮어쓰지 않는다.
"""
from __future__ import annotations

import datetime as dt
import json
import re

import numpy as np
import yaml

from .. import store
from ..config import CONFIG, ROOT, criterion_from_dict, load_categories, load_criterion_raw
from . import evaluate as ev
from . import propose as pr
from . import scout as sc
from .cost import Budget

HYP_DIR = CONFIG / "hypotheses"
# 봉인(2026-11-03 검토 반영): 마지막 정답 구간(2021→24)은 가설 선택·adopt 에서 절대 보지 않는다.
# 선택용 창은 2012~2018(정답이 2021년에 끝남). 봉인 구간 성적은 `sealed` 명령/hit_rate.py 로만 확인.
SEAL_FROM = 2021
H = 3
STARTS = tuple(range(2012, SEAL_FROM - H + 1))
YEARS = list(range(2005, 2025))


def out_dir(category):
    d = ROOT / "outputs" / "agent" / category
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_hypotheses() -> dict[str, dict]:
    return {p.stem: yaml.safe_load(p.read_text()) for p in sorted(HYP_DIR.glob("*.yaml"))}


def save_hypothesis(h: dict) -> str:
    HYP_DIR.mkdir(parents=True, exist_ok=True)
    hid = re.sub(r"[^0-9a-zA-Z_]+", "_", h["id"]).strip("_").lower()
    hid = hid if hid.startswith("auto_") else "auto_" + hid  # LLM 이 id 에 auto_ 를 넣어 와도 한 번만
    h = dict(h, id=hid, created=dt.date.today().isoformat())
    (HYP_DIR / f"{hid}.yaml").write_text(yaml.safe_dump(h, allow_unicode=True, sort_keys=False))
    return hid


def ledger(category) -> list[dict]:
    p = out_dir(category) / "ledger.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []


def _log(category, rec):
    rec = dict(rec, at=dt.datetime.now().isoformat(timespec="seconds"))
    with (out_dir(category) / "ledger.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=float) + "\n")


def panel_for(category, raw, fetch=True, log=print):
    cats = load_categories()
    return store.assemble_panel(category, {category: cats[category]}, criterion_from_dict(raw), YEARS, fetch=fetch, log=log)


def _base(criterion, kw):
    raw = load_criterion_raw(criterion)
    if kw.get("target_kind"):  # abs = 증가액(큰 시장 유리), log = 증가율(성장 신호 유리)
        raw["target"] = dict(raw.get("target", {}), kind=kw["target_kind"])
    return raw


def test(hyp_id, category="dry_confectionery", criterion="k_export", fetch=True, log=print, **kw) -> dict:
    hyp = load_hypotheses()[hyp_id]
    base_raw = _base(criterion, kw)
    panel = panel_for(category, ev.augment(base_raw, hyp["indicators"]), fetch, log)
    res = ev.evaluate(panel, store.countries(fetch), base_raw, hyp, category, starts=kw.get("starts", STARTS),
                      n_fit=kw.get("n_fit", 8000), B=kw.get("B", 500))
    res["target_kind"] = base_raw["target"].get("kind", "abs")
    (out_dir(category) / f"{hyp_id}.json").write_text(json.dumps(res, ensure_ascii=False, default=float, indent=1))
    (out_dir(category) / f"{hyp_id}__{res['target_kind']}.json").write_text(json.dumps(res, ensure_ascii=False, default=float, indent=1))
    _log(category, {"hypothesis": hyp_id, "statement": hyp.get("statement", ""), "proposed_by": hyp.get("proposed_by", ""),
                    "target_kind": res["target_kind"], "status": res["status"], "oos": res.get("oos"), "reason": res["reason"]})
    log(res["reason"])
    return res


def loop(category="dry_confectionery", criterion="k_export", rounds=1, n=3, fetch=True, llm=None, log=print, **kw):
    """LLM이 가설을 내고 → 검증하고 → 기록하는 과정을 rounds 번 반복."""
    base_raw = _base(criterion, kw)
    countries = store.countries(fetch)
    for r in range(rounds):
        panel = panel_for(category, base_raw, fetch, log)
        ok, dropped, prompt = pr.propose(panel, countries, base_raw, category, ledger(category),
                                         t=max(kw.get("starts", STARTS)), n=n, llm=llm)
        (out_dir(category) / f"prompt_round{r + 1}.txt").write_text(prompt, encoding="utf-8")
        for h in dropped:
            hid = save_hypothesis(h)
            _log(category, {"hypothesis": hid, "statement": h["statement"], "proposed_by": h["proposed_by"],
                            "status": "data_needed", "reason": h["reason"]})
            log(f"[agent] {hid}: 데이터 필요 - {h['reason']}")
        for h in ok:
            hid = save_hypothesis(h)
            log(f"[agent] 라운드 {r + 1} 가설 {hid}: {h['statement']}")
            test(hid, category, criterion, fetch, log, **kw)
    return ledger(category)


def auto(category="dry_confectionery", criterion="k_export", max_rounds=6, n=3, patience=2, budget_usd=1.0, fetch=True,
         scout_share=0.3, llm=None, client=None, scout_fn=None, log=print, **kw) -> dict:
    """사람이 라운드 수를 정하지 않는 자율 실행.
    라운드마다: 가설 제안 → 데이터가 없으면 데이터 탐색 에이전트가 웹에서 찾아 등록 → 검증 → 기록.
    멈추는 조건(에이전트가 스스로 판단): ① 채택이 patience 라운드 연속 없음(개선 정체) ② 예산 소진 ③ max_rounds.
    끝나면 채택분이 있을 때 adopt, 그리고 report."""
    budget = Budget(budget_usd)
    base_raw = _base(criterion, kw)
    countries = store.countries(fetch)
    starts = kw.get("starts", STARTS)
    scout_fn = scout_fn or sc.scout
    rounds, stale, stop = [], 0, f"최대 {max_rounds}라운드 도달"
    for r in range(max_rounds):
        if budget.exhausted(reserve=0.3):
            stop = f"예산 소진(${budget.spent:.2f}/${budget.limit:.2f})"
            break
        panel = panel_for(category, base_raw, fetch, log)
        ok, dropped, prompt = pr.propose(panel, countries, base_raw, category, ledger(category), t=max(starts), n=n,
                                         llm=llm or (lambda p: pr.call_llm(p, budget)))
        (out_dir(category) / f"prompt_auto_{budget.run}_r{r + 1}.txt").write_text(prompt, encoding="utf-8")
        found = {}
        for h in dropped:  # 데이터가 없어 걸러진 가설 → 데이터 탐색
            hid = save_hypothesis(h)
            names = {c["series"] for c in pr.external.catalog()}
            need = sorted({i["series"] for i in h["indicators"] if i["source"] == "external" and i["series"] not in names})
            got = True
            for series in need:
                if budget.exhausted(reserve=0.3):
                    got = False
                    _log(category, {"hypothesis": hid, "statement": h["statement"], "proposed_by": h["proposed_by"],
                                    "status": "scout_budget", "reason": f"'{series}' 탐색 전 예산 소진(${budget.spent:.2f})"})
                    continue
                log(f"[auto] {hid}: '{series}' 데이터 탐색 시작")
                sub = Budget(min(budget.left, budget.limit * scout_share), run=budget.run, path=budget.path)
                res = scout_fn(series, h.get("new_source_needed", ""), h, YEARS, sub, client=client, log=log)
                budget.spent += sub.spent
                budget.calls += sub.calls
                found[series] = res["status"]
                _log(category, {"hypothesis": hid, "statement": h["statement"], "proposed_by": h["proposed_by"],
                                "status": f"scout_{res['status']}",
                                "reason": json.dumps({k: v for k, v in res.items() if k != "trace"}, ensure_ascii=False, default=str)[:1500]})
                got = got and res["status"] == "registered"
            if got and pr.validate(h)[0]:
                ok.append(dict(h, id=hid))
            elif not need:
                _log(category, {"hypothesis": hid, "statement": h["statement"], "proposed_by": h["proposed_by"],
                                "status": "data_needed", "reason": h["reason"]})
        statuses = {}
        for h in ok:
            hid = save_hypothesis(h)
            res = test(hid, category, criterion, fetch, log, **kw)
            statuses[hid] = res["status"]
        accepted = [k for k, v in statuses.items() if v == "accepted"]
        rounds.append({"round": r + 1, "tested": statuses, "scouted": found, "spent": round(budget.spent, 3)})
        log(f"[auto] 라운드 {r + 1}: 검증 {statuses}, 데이터 탐색 {found}, 누적 ${budget.spent:.2f}")
        stale = 0 if accepted else stale + 1
        if stale >= patience:
            stop = f"{patience}라운드 연속 채택 없음(개선 정체)"
            break
    log(f"[auto] 종료: {stop}")
    any_acc = any(r.get("status") == "accepted" for r in ledger(category))  # 이번 실행 이전 채택분도 포함
    adopted = adopt(category, criterion, fetch=fetch, log=log, **kw) if any_acc else None
    summary = {"run": budget.run, "stop": stop, "rounds": rounds, "spent_usd": round(budget.spent, 3),
               "api_calls": budget.calls, "adopt": adopted}
    (out_dir(category) / f"auto_{budget.run}.json").write_text(json.dumps(summary, ensure_ascii=False, default=float, indent=1))
    _log(category, {"hypothesis": "auto", "status": "auto_end", "reason": f"{stop}; ${budget.spent:.2f}, 호출 {budget.calls}회"})
    report(category)
    return summary


def _compare(panel, countries, raw_a, raw_b, category, starts, n_fit, B, seed=0):
    a, b = criterion_from_dict(raw_a), criterion_from_dict(raw_b)
    wa, wb = ev._windows(panel, countries, a, category, starts, n_fit, seed), ev._windows(panel, countries, b, category, starts, n_fit, seed)
    ev._fit_all(wa, n_fit, seed)
    ev._fit_all(wb, n_fit, seed)
    pairs, summ = ev._oos(wa, wb, a.target.get("horizon", 3), B, np.random.default_rng(seed))
    return pairs, summ, wb


def adopt(category="dry_confectionery", criterion="k_export", prune_below=0.03, fetch=True, log=print, **kw) -> dict:
    """채택된 가설의 지표를 합치고, 평균 가중치가 prune_below 미만인 지표를 빼서 새 기준을 만든다."""
    hyps, base_raw = load_hypotheses(), _base(criterion, kw)
    latest = {}
    for rec in ledger(category):
        latest[rec["hypothesis"]] = rec
    add = []
    for hid, rec in latest.items():
        if rec["status"] != "accepted" or hid not in hyps:
            continue
        res = json.loads((out_dir(category) / f"{hid}.json").read_text())
        if max(res.get("windows") or [9999]) > max(kw.get("starts", STARTS)):
            log(f"[adopt] {hid}: 봉인 구간까지 본 옛 검증 결과라 제외 → `agent test --hyp {hid}` 로 다시 검증하세요")
            continue
        solo = res.get("solo") or {}
        for i in hyps[hid]["indicators"]:
            if not solo or (solo.get(i["id"], {}).get("status") in ("accepted", "weak")):
                add.append(i)
    if not add:
        log("[adopt] 채택된 지표 없음 → 기준 유지")
        return {"added": [], "dropped": []}
    cand_raw = ev.augment(base_raw, add)
    panel = panel_for(category, cand_raw, fetch, log)
    countries = store.countries(fetch)
    starts, n_fit, B = kw.get("starts", STARTS), kw.get("n_fit", 8000), kw.get("B", 500)
    _, _, wins = _compare(panel, countries, base_raw, cand_raw, category, starts, n_fit, B)
    ids = [i["id"] for i in cand_raw["indicators"]]
    mean_w = np.mean([w["w"] for w in wins.values()], axis=0)
    drop = [i for i, w in zip(ids, mean_w) if w < prune_below]
    final_raw = dict(cand_raw, id=f"{criterion}_agent", name_ko=cand_raw["name_ko"] + " · 에이전트 갱신",
                     indicators=[i for i in cand_raw["indicators"] if i["id"] not in drop],
                     selection={"last_start": max(starts), "seal_from": SEAL_FROM,
                                "note": "지표 선택·가지치기에 쓴 마지막 창. last_start+3 < seal_from 이면 봉인 구간은 미사용"})
    pairs, summ, _ = _compare(panel, countries, base_raw, final_raw, category, starts, n_fit, B)
    better = summ is not None and summ["mean_delta"] >= 0
    rep = {"added": [i["id"] for i in add], "dropped": drop, "mean_weights": dict(zip(ids, np.round(mean_w, 3).tolist())),
           "oos_vs_base": summ, "oos_pairs": pairs, "written": better}
    if better:
        (CONFIG / "criteria" / f"{criterion}_agent.yaml").write_text(
            "# 에이전트가 생성한 기준(adopt). 원본 기준은 그대로 둔다.\n" + yaml.safe_dump(final_raw, allow_unicode=True, sort_keys=False))
    (out_dir(category) / "adopt.json").write_text(json.dumps(rep, ensure_ascii=False, default=float, indent=1))
    _log(category, {"hypothesis": "adopt", "status": "written" if better else "kept_base",
                    "reason": f"추가 {rep['added']}, 제거 {drop}, 기존 대비 표본 밖 {summ['mean_delta'] if summ else None}"})
    log(json.dumps(rep, ensure_ascii=False, default=float)[:2000])
    return rep


def sealed(category="dry_confectionery", criterion="k_export", fetch=False, log=print, **kw) -> dict:
    """봉인 구간 시험: 2018년 창으로 찾은 가중치가 2021→24 수출 증가를 맞혔나(기존 기준 vs 에이전트 기준)."""
    base_raw = _base(criterion, kw)
    agent_raw = load_criterion_raw(f"{criterion}_agent")
    if kw.get("target_kind"):
        agent_raw["target"] = dict(agent_raw.get("target", {}), kind=kw["target_kind"])
    last = agent_raw.get("selection", {}).get("last_start", 9999)
    valid = last <= SEAL_FROM - H  # 선택에 쓴 마지막 창의 정답이 봉인 시작 전에 끝남
    panel = panel_for(category, ev.augment(base_raw, agent_raw["indicators"]), fetch, log)
    pairs, summ, _ = _compare(panel, store.countries(fetch), base_raw, agent_raw, category, (SEAL_FROM - H, SEAL_FROM),
                              kw.get("n_fit", 8000), kw.get("B", 500))
    rep = {"seal_test": f"{SEAL_FROM}->{SEAL_FROM + H}", "fit": SEAL_FROM - H, "valid": valid, "selection_last_start": last,
           "target_kind": base_raw["target"].get("kind", "abs"), "pairs": pairs, "summary": summ}
    if not valid:
        rep["warning"] = "에이전트 기준이 봉인 구간을 본 상태로 만들어짐 → agent test(기본 창) 재실행 후 adopt 다시"
    (out_dir(category) / f"sealed__{rep['target_kind']}.json").write_text(json.dumps(rep, ensure_ascii=False, default=float, indent=1))
    log(json.dumps(rep, ensure_ascii=False, default=float))
    return rep


def report(category="dry_confectionery") -> str:
    rows = ledger(category)
    label = {"accepted": "채택", "weak": "보류", "rejected": "기각", "data_needed": "데이터 필요", "written": "모델 갱신", "kept_base": "기존 유지",
             "scout_registered": "데이터 찾아 등록", "scout_gave_up": "데이터 못 찾음", "scout_budget": "예산으로 탐색 중단",
             "scout_steps": "탐색 횟수 초과", "scout_refusal": "탐색 거절", "auto_end": "자율 실행 종료"}
    md = [f"# 에이전트 검증 기록 ({category})", "", "| 시각 | 가설 | 제안 | 판정 | 표본 밖 개선 | 우위 확률 |", "|---|---|---|---|---|---|"]
    for r in rows:
        o = r.get("oos") or {}
        md.append(f"| {r['at']} | {r['hypothesis']} | {r.get('proposed_by', '')} | {label.get(r['status'], r['status'])} | "
                  f"{o.get('mean_delta', float('nan')):+.3f} | {o.get('p_better', float('nan')) * 100:.0f}% |" if o else
                  f"| {r['at']} | {r['hypothesis']} | {r.get('proposed_by', '')} | {label.get(r['status'], r['status'])} | - | - |")
    md += ["", "## 판정 근거", ""]
    for r in rows:
        md += [f"### {r['hypothesis']} — {label.get(r['status'], r['status'])}", r.get("statement", ""), "", "```", r.get("reason", ""), "```", ""]
    text = "\n".join(md)
    (out_dir(category) / "report.md").write_text(text, encoding="utf-8")
    return text
