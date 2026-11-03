"""역산 검증.

1) 시점 재현: 실제 진출연도-1 기준으로 같은 모델을 다시 돌려, 실제 진출국 순위와 모델 1위국을 비교하고
   두 나라의 지표 차이(백분위 차)를 큰 순서로 보여준다.
2) 가중치 역산: 가중치 조합(심플렉스 격자)을 전부 시도해 '실제 진출국이 가장 높은 순위에 오르는' 가중치를 찾는다.
   사례 수가 적으므로 단일 최적값보다 상위 1% 조합의 평균·범위(=설명 가능한 가중치 영역)를 함께 보고한다.
3) 신규 지표 후보 검토: 후보 지표를 6번째로 넣었을 때 설명력이 얼마나 오르는지, 실제 진출국이 그 지표에서
   일관되게 높거나 낮았는지를 본다.
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from .config import Criterion
from .scoring import score


def simplex_grid(k: int, step: float) -> np.ndarray:
    n = int(round(1 / step))
    out = []
    for c in itertools.combinations(range(n + k - 1), k - 1):
        parts, prev = [], -1
        for x in c:
            parts.append(x - prev - 1)
            prev = x
        parts.append(n + k - 1 - prev - 1)
        out.append(parts)
    return np.array(out, dtype=float) / n


def _event_matrices(events, ids):
    """각 사례: (국가×지표 백분위 행렬, 실제국 행 인덱스)."""
    mats = []
    for ev in events:
        pct = ev["pct"]
        if ev["iso3"] not in pct.index:
            continue
        P = pct[ids].fillna(50.0).to_numpy()
        mats.append((P, pct.index.get_loc(ev["iso3"])))
    return mats


def evaluate_weights(mats, W: np.ndarray) -> np.ndarray:
    """W: (K×d). 반환: (사례×K) 실제국 백분위 순위(1=전체 1위, 0=꼴찌)."""
    res = []
    for P, a in mats:
        S = P @ W.T  # N×K
        res.append((S < S[a]).sum(axis=0) / (len(P) - 1))
    return np.array(res)


def run(panel, countries, criterion: Criterion, category: str, entries: dict,
        weights: dict | None = None, grid_step: float = 0.05):
    weights = weights or criterion.weights
    core = [i.id for i in criterion.indicators]
    cand = [i.id for i in criterion.candidates]
    names = {i.id: i.name_ko for i in criterion.all_indicators()}

    events = []
    for e in entries["entries"]:
        as_of = e["year"] - 1
        table, raw, pct = score(panel, countries, criterion, category, as_of, weights)
        ev = {**e, "as_of": as_of, "table": table, "raw": raw, "pct": pct, "n": len(table)}
        if e["iso3"] in table.index:
            top1 = table.index[0]
            ev["rank"] = int(table.loc[e["iso3"], "rank"])
            ev["top1"] = top1
            ev["top3"] = list(table.index[:3])
            gap = pd.DataFrame({
                "지표": [names[c] for c in core + cand],
                "구분": ["핵심"] * len(core) + ["후보"] * len(cand),
                "실제국_백분위": pct.loc[e["iso3"], core + cand].values,
                "모델1위_백분위": pct.loc[top1, core + cand].values,
                "실제국_원값": raw.loc[e["iso3"], core + cand].values,
                "모델1위_원값": raw.loc[top1, core + cand].values,
            }, index=core + cand)
            gap["차이(실제-1위)"] = gap["실제국_백분위"] - gap["모델1위_백분위"]
            ev["gap"] = gap.reindex(gap["차이(실제-1위)"].abs().sort_values(ascending=False).index)
        else:
            ev["rank"] = None
        events.append(ev)

    used = [ev for ev in events if ev.get("include", True) and ev["rank"] is not None]
    mats = _event_matrices(used, core)

    # --- 가중치 역산 ---
    W = simplex_grid(len(core), grid_step)
    R = evaluate_weights(mats, W)          # 사례×K
    obj = R.mean(axis=0)
    order = np.argsort(-obj)
    top = order[: max(1, len(order) // 100)]
    w_def = np.array([weights.get(c, 0) for c in core], float)
    w_def = w_def / w_def.sum()
    def_obj = evaluate_weights(mats, w_def[None, :]).mean()
    inverse = {
        "best_weights": dict(zip(core, W[order[0]].round(3))),
        "best_mean_percentile": float(obj[order[0]]),
        "robust_mean": dict(zip(core, W[top].mean(axis=0).round(3))),
        "robust_min": dict(zip(core, W[top].min(axis=0).round(3))),
        "robust_max": dict(zip(core, W[top].max(axis=0).round(3))),
        "default_weights": dict(zip(core, w_def.round(3))),
        "default_mean_percentile": float(def_obj),
        "n_events": len(mats),
        "n_combinations": len(W),
    }
    # 사례별 최적 가중치에서의 순위
    best_w = W[order[0]]
    per_event = []
    for ev in used:
        P = ev["pct"][core].fillna(50.0)
        s = (P @ best_w)
        rk = int((s > s[ev["iso3"]]).sum() + 1)
        per_event.append({"iso3": ev["iso3"], "country_ko": ev["country_ko"], "year": ev["year"],
                          "rank_default": ev["rank"], "rank_inverse": rk, "n": ev["n"]})
    inverse["per_event"] = per_event
    # leave-one-out 안정성
    loo = []
    for j in range(len(mats)):
        o = np.delete(R, j, axis=0).mean(axis=0)
        loo.append(dict(zip(core, W[int(np.argmax(o))].round(2))))
    inverse["leave_one_out"] = loo

    # --- 신규 지표 후보 검토 ---
    W5 = simplex_grid(len(core), 0.1)
    base = evaluate_weights(mats, W5).mean(axis=0).max()
    W6 = simplex_grid(len(core) + 1, 0.1)
    cand_rows = []
    for c in cand:
        m6 = _event_matrices(used, core + [c])
        o6 = evaluate_weights(m6, W6).mean(axis=0)
        b = int(np.argmax(o6))
        p = [ev["pct"].loc[ev["iso3"], c] for ev in used]
        p = [x for x in p if pd.notna(x)]
        cand_rows.append({
            "id": c, "지표": names[c],
            "실제국_평균백분위": float(np.mean(p)) if p else np.nan,
            "50초과_사례수": int(sum(x > 50 for x in p)), "사례수": len(p),
            "추가시_설명력": float(o6[b]), "기존_설명력": float(base),
            "개선폭(%p)": float((o6[b] - base) * 100), "추가시_가중치": float(W6[b][-1]),
        })
    cands = pd.DataFrame(cand_rows).sort_values("개선폭(%p)", ascending=False)

    return events, inverse, cands
