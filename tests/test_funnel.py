"""깔때기: 가짜 나라로 단계 규칙 확인 (원천 데이터 불필요)."""
import numpy as np
import pandas as pd

from kfood_scout.funnel.core import pct_scores, perturb, top_share

G = {"a": {"weight": 0.5, "indicators": {"x": 1.0}}, "b": {"weight": 0.5, "indicators": {"distance_km": 1.0}}}


def test_pct_direction_and_missing():
    T = pd.DataFrame({"x": [1, 2, 3, np.nan], "distance_km": [100, 200, 300, 400]}, index=list("ABCD"))
    tot, Gs, P = pct_scores(T, list("ABCD"), G)
    assert P.at["D", "x"] == 50.0                     # 결측은 중립
    assert P.at["A", "distance_km"] > P.at["D", "distance_km"]   # 가까울수록 높은 점수
    assert tot.idxmax() in ("A", "C")


def test_top_share_rounds_up():
    s = pd.Series([5, 4, 3, 2, 1], index=list("ABCDE"))
    assert top_share(s, 0.5) == ["A", "B", "C"]


def test_perturb_keeps_sums():
    out = perturb(G, np.random.default_rng(0), 20)
    assert abs(sum(g["weight"] for g in out.values()) - 1) < 1e-9
    assert all(abs(sum(g["indicators"].values()) - 1) < 1e-9 for g in out.values())
