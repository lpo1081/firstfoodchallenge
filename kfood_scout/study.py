"""비교 설계(study) 실행기.

study YAML 의 axes(카테고리 × 기준 × 방법 …)를 곱해 '실행 단위(run)'를 만들고,
각 run 을 독립적으로 계산해 outputs/studies/<study>/runs/<run_id>.json 에 저장한다.
- 축에 값을 추가/삭제 → 그 조합만 새로 계산(설정·데이터가 같으면 이전 결과 재사용).
- 새 방법(method)은 METHODS 에 함수 하나 등록.
- 새 축(예: 비교 기업, 목표 지표)은 apply_axis 에 규칙 하나 추가.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json

import pandas as pd

from . import rolling, store
from .config import ROOT, criterion_from_dict, load_categories, load_criterion_raw, load_entries, load_study


# ---------- 방법 레지스트리 ----------
def _rolling(panel, countries, crit, category, params, existing):
    return rolling.run(panel, countries, crit, category, starts=tuple(params.get("starts", (2012, 2015, 2018, 2021))),
                       forecast_year=params.get("forecast_year", 2024), existing=existing)


METHODS = {"rolling": _rolling}


# ---------- 축 → 설정 ----------
def apply_axis(ctx: dict, axis: str, value, study: dict, cats: dict):
    """축 값 하나를 실행 설정(ctx)에 반영. 새 축은 여기에 분기 하나만 추가."""
    if axis == "category":
        ctx["category_id"], ctx["category"] = value, copy.deepcopy(cats[value])
    elif axis == "criterion":
        ctx["criterion"] = load_criterion_raw(value)
    elif axis == "method":
        ctx["method_id"], ctx["method"] = value, copy.deepcopy(study.get("methods", {}).get(value, {}))
    elif axis == "target":  # 예: KOR_X 증가액(abs) vs 성장률(log)
        ctx.setdefault("criterion", {}).setdefault("target", {}).update(study["targets"][value])
    else:
        raise KeyError(f"모르는 축: {axis} (study.apply_axis 에 규칙 추가)")


def _set_dotted(ctx: dict, path: str, value):
    head, *rest = path.split(".")
    node = ctx[{"criterion": "criterion", "method": "method", "category": "category"}[head]]
    for k in rest[:-1]:
        node = node.setdefault(k, {})
    node[rest[-1]] = value


def run_id(combo: dict) -> str:
    return "__".join(f"{k}={v}" for k, v in combo.items())


def expand(study: dict) -> list[dict]:
    """axes 곱 → run 목록. 각 run = {'combo': {...}, 'ctx': 실행 설정}."""
    cats = load_categories()
    axes = study["axes"]
    order = ["criterion"] + [a for a in axes if a != "criterion"]  # target 축이 criterion 위에 덮어쓰도록
    runs = []
    for values in itertools.product(*axes.values()):
        combo = dict(zip(axes.keys(), values))
        ctx = {}
        for a in order:
            if a in combo:
                apply_axis(ctx, a, combo[a], study, cats)
        for ov in study.get("overrides") or []:
            if all(combo.get(k) == v for k, v in ov["when"].items()):
                for path, v in ov["set"].items():
                    _set_dotted(ctx, path, v)
        runs.append({"id": run_id(combo), "combo": combo, "ctx": ctx})
    return runs


def years_of(study: dict) -> list[int]:
    a, b = study.get("data", {}).get("years", [2005, 2024])
    return list(range(a, b + 1))


def plan(study_name: str) -> list[dict]:
    """수집 계획: run 별 남은 Comtrade 호출 수(이미 받은 HS 코드는 0)."""
    study, years, out, seen = load_study(study_name), None, [], set()
    years = years_of(study)
    for r in expand(study):
        crit = criterion_from_dict(r["ctx"]["criterion"])
        cats = {r["combo"]["category"]: r["ctx"]["category"]}
        n = store.needs(r["combo"]["category"], cats, crit)
        key = (tuple(n["hs"]), tuple(n["flows"]))
        calls = 0 if key in seen else store.pending_calls(r["combo"]["category"], cats, crit, years)
        seen.add(key)
        out.append({"run": r["id"], "hs": n["hs"], "flows": n["flows"], "pending_calls": calls})
    return out


def _fingerprint(ctx, panel) -> str:
    h = hashlib.sha1(json.dumps(ctx, sort_keys=True, ensure_ascii=False, default=str).encode())
    h.update(str(int(pd.util.hash_pandas_object(panel.sort_values(["series", "iso3", "year"]), index=False).sum())).encode())
    return h.hexdigest()[:12]


def _context(panel, category, years):
    """해석용 맥락: 연도별 한국 수출 총액, 세계 수입 총액."""
    out = {}
    for flow in ("KOR_X", "M"):
        s = panel[panel.series == f"CT:{category}:{flow}"].groupby("year")["value"].sum()
        out[flow] = {int(y): float(v) for y, v in s.items() if y in years}
    return out


def run_study(study_name: str, fetch: bool = True, only: dict | None = None, force: bool = False, log=print) -> dict:
    study = load_study(study_name)
    years = years_of(study)
    countries = store.countries(fetch)
    existing = {e["iso3"] for e in load_entries(study["entries"])["entries"]} if study.get("entries") else set()
    d = ROOT / "outputs" / "studies" / study_name / "runs"
    d.mkdir(parents=True, exist_ok=True)
    results = {}
    for r in expand(study):
        if only and any(r["combo"].get(k) != v for k, v in only.items()):
            continue
        ctx, cat = r["ctx"], r["combo"]["category"]
        crit = criterion_from_dict(ctx["criterion"])
        panel = store.assemble_panel(cat, {cat: ctx["category"]}, crit, years, fetch=fetch, log=log)
        fp, path = _fingerprint(ctx, panel), d / f"{r['id']}.json"
        if path.exists() and not force and json.loads(path.read_text()).get("fingerprint") == fp:
            log(f"[study] {r['id']}: 변경 없음, 이전 결과 재사용")
            results[r["id"]] = json.loads(path.read_text())
            continue
        log(f"[study] {r['id']}: 계산")
        try:
            res = METHODS[r["combo"].get("method", "rolling")](panel, countries, crit, cat, ctx.get("method", {}), existing)
            res["error"] = None
        except ValueError as e:  # 데이터 부족 등은 비교표에 '불가'로 남기고 계속
            res = {"error": str(e)}
        res.update({"run_id": r["id"], "combo": r["combo"], "fingerprint": fp,
                    "category_name": ctx["category"]["name_ko"], "hs_codes": ctx["category"]["hs_codes"],
                    "context": _context(panel, cat, years)})
        path.write_text(json.dumps(res, ensure_ascii=False, default=float), encoding="utf-8")
        results[r["id"]] = res
    return results
