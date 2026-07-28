from datetime import date

import pytest

from core.evaluate import evaluate
from core.scenarios import (
    peer_waterfall,
    remaining_path_scenarios,
    score_matrix,
    score_timeseries,
    sensitivity_table,
    target_price,
)

EVAL_DATE = date(2026, 7, 15)


def test_score_matrix_has_12_cells(prices, universe, rules, calibration):
    rows = score_matrix(prices, universe, rules, calibration, EVAL_DATE)
    assert len(rows) == 12
    assert {r["mode"] for r in rows} == {"잠정", "최종"}
    assert {r["method"] for r in rows} == {"A", "B"}
    assert {r["baseline"] for r in rows} == {"V1", "V2", "V3"}


def test_score_matrix_matches_engine(prices, universe, rules, calibration):
    rows = score_matrix(prices, universe, rules, calibration, EVAL_DATE)
    want = evaluate(prices, universe, rules, calibration, EVAL_DATE, "최종", "B")
    got = next(r for r in rows if r["mode"] == "최종" and r["method"] == "B" and r["baseline"] == "V3")
    assert got["value"] == pytest.approx(want.scores["V3"].value, abs=0.01)


def test_waterfall_reconciles_to_actual_score(prices, universe, rules, calibration):
    steps = peer_waterfall(prices, universe, rules, calibration, EVAL_DATE, "잠정", "B")
    assert len(steps) == 1 + 8  # 출발점 + 8개 Peer
    want = evaluate(prices, universe, rules, calibration, EVAL_DATE, "잠정", "B").scores["V3"].value
    assert steps[-1]["score"] == pytest.approx(want, abs=0.01)
    # 단계 합 = 최종 - 출발
    total_delta = sum(s["delta"] for s in steps[1:])
    assert total_delta == pytest.approx(steps[-1]["score"] - steps[0]["score"], abs=0.01)


def test_waterfall_groups_in_order(prices, universe, rules, calibration):
    steps = peer_waterfall(prices, universe, rules, calibration, EVAL_DATE, "최종", "B")
    groups = [s["group"] for s in steps[1:]]
    assert groups == ["에화"] * 4 + ["배소"] * 4


def test_sensitivity_base_score_matches_engine(prices, universe, rules, calibration):
    sens = sensitivity_table(prices, universe, rules, calibration, EVAL_DATE, "잠정", "B")
    want = evaluate(prices, universe, rules, calibration, EVAL_DATE, "잠정", "B").scores["V3"].value
    assert sens["base_score"] == pytest.approx(want, abs=0.01)


def test_sensitivity_sk_up_raises_score(prices, universe, rules, calibration):
    """잠정 방식 7/15 는 원값이 0점 아래로 깊이 떨어져 클리핑 바닥에 붙어 있어
    ±1%p 로는 안 움직인다(§3 편향) — 최종 방식으로 확인한다."""
    sens = sensitivity_table(prices, universe, rules, calibration, EVAL_DATE, "최종", "B")
    up = next(r for r in sens["rows"] if r["target"] == "SK이노베이션" and r["shift"] == "+1%p")
    down = next(r for r in sens["rows"] if r["target"] == "SK이노베이션" and r["shift"] == "-1%p")
    assert up["delta"] > 0
    assert down["delta"] < 0


def test_sensitivity_peer_up_lowers_score(prices, universe, rules, calibration):
    sens = sensitivity_table(prices, universe, rules, calibration, EVAL_DATE, "최종", "B")
    up = next(r for r in sens["rows"] if r["target"] == "에화 그룹" and r["shift"] == "+1%p")
    assert up["delta"] < 0


def test_target_price_roundtrips_actual_score(prices, universe, rules, calibration):
    """실제 원값 점수를 목표로 역산하면 실제 SK 보정주가가 그대로 나와야 한다."""
    actual = evaluate(prices, universe, rules, calibration, EVAL_DATE, "잠정", "B")
    tp = target_price(prices, universe, rules, calibration, EVAL_DATE, "잠정", "B",
                       actual.scores["V3"].raw)
    assert tp["needed_vwap"] == pytest.approx(tp["current_vwap"], abs=1.0)


def test_target_price_100_needs_higher_price_than_current(prices, universe, rules, calibration):
    tp = target_price(prices, universe, rules, calibration, EVAL_DATE, "잠정", "B", 100)
    assert tp["needed_vwap"] > tp["current_vwap"]


def test_score_timeseries_ends_at_official_score(prices, universe, rules, calibration):
    days = [date(2025, 12, 30), date(2026, 7, 15)]
    series = score_timeseries(prices, universe, rules, calibration, days, "B")
    assert series[-1]["date"] == "2026-07-15"
    want = evaluate(prices, universe, rules, calibration, EVAL_DATE, "잠정", "B").scores["V3"].value
    assert series[-1]["value"] == pytest.approx(want, abs=0.01)


def test_score_timeseries_skips_days_before_base(prices, universe, rules, calibration):
    days = [date(2025, 10, 1), date(2025, 12, 30)]
    series = score_timeseries(prices, universe, rules, calibration, days, "B")
    assert len(series) == 1
    assert series[0]["date"] == "2025-12-30"


def test_remaining_path_scenarios_ordered_up_flat_down(prices, universe, rules, calibration):
    """Peer 고정 가정에서, SK 가 더 오르는 경로일수록 점수도 높아야 한다."""
    as_of = date(2026, 7, 27)
    r = remaining_path_scenarios(prices, universe, rules, calibration, as_of, 3, "B")
    up, flat, down = (s["value"] for s in r["scenarios"])
    assert up > flat > down


def test_remaining_path_lock_in_shrinks_with_longer_horizon(prices, universe, rules, calibration):
    """평가일이 멀수록(윈도우가 통째로 미래) 고착도가 낮아야 한다."""
    as_of = date(2026, 7, 27)
    near = remaining_path_scenarios(prices, universe, rules, calibration, as_of, 1, "B")
    far = remaining_path_scenarios(prices, universe, rules, calibration, as_of, 3, "B")
    assert near["lock_in_pct"] > far["lock_in_pct"]
    assert 0.0 <= far["lock_in_pct"] <= 1.0
