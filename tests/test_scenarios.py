from datetime import date, timedelta

import pytest

from core.evaluate import evaluate
from core.scenarios import (
    flat_projection_prices,
    peer_waterfall,
    remaining_path_scenarios,
    score_matrix,
    score_timeseries,
    sensitivity_table,
    target_price,
)
from core.schema import Bar
from pipeline.build_site import build_year_end_estimate

EVAL_DATE = date(2026, 7, 15)


def test_score_matrix_has_final_primary_baselines(prices, universe, rules, calibration):
    rows = score_matrix(prices, universe, rules, calibration, EVAL_DATE)
    assert len(rows) == 3
    assert {r["mode"] for r in rows} == {"최종"}
    assert {r["method"] for r in rows} == {rules["vwap_primary"]}
    assert {r["baseline"] for r in rows} == {"V1", "V2", "V3"}
    assert all(r["anchor"] > 0 for r in rows)


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


def test_year_end_flat_uses_each_tickers_nov26_price_and_volume(prices, universe, rules, calibration):
    s = build_year_end_estimate(prices, universe, rules, calibration)
    assert (s["as_of"], s["cutoff_date"], s["eval_date"]) == ("2026-11-26", "2026-12-31", "2026-12-30")
    sessions = [date.fromisoformat(d) for d in s["trading_dates"]]
    assert len(sessions) == 23
    assert sessions[0] == date(2026, 11, 27)
    assert all(d.weekday() < 5 and d != date(2026, 12, 25) for d in sessions)

    # Independently compute the three-window average: 1M and 1W are fully projected.
    rows = [s["subject"], *(r for g in s["groups"].values() for r in g["members"])]
    for row in rows:
        actual = [b for b in prices[row["code"]] if date(2026, 11, 2) <= b.day <= date(2026, 11, 26)]
        last = actual[-1]
        assert (row["close"], row["volume"]) == (last.close, last.volume)
        future_volume = 23 * last.volume
        two_month = (sum(b.close * b.volume for b in actual) + last.close * future_volume) / (
            sum(b.volume for b in actual) + future_volume
        )
        assert row["price"] == pytest.approx((two_month + 2 * last.close) / 3, abs=0.005)
    assert [(w["actual_days"], w["projected_days"]) for w in s["windows"]] == [(19, 23), (0, 21), (0, 5)]
    assert s["peer_change"] == pytest.approx(0.6 * s["group_changes"]["에화"] + 0.4 * s["group_changes"]["배소"], abs=1e-6)
    assert s["eval_price"] == pytest.approx(s["subject_price"] / (1 - (s["subject_change"] - s["peer_change"])), abs=0.15)
    assert s["scores"]["V2"]["anchor"] == calibration["baselines"]["V2"]["value"]


def test_year_end_scenario_does_not_follow_later_daily_updates(prices, universe, rules, calibration):
    as_of = date(2026, 11, 26)
    future = as_of + timedelta(days=1)
    known = {code: [b for b in bars if b.day <= as_of] for code, bars in prices.items()}
    newer = {code: bars + [Bar(future, 1200, 2, 2400)] for code, bars in known.items()}
    assert build_year_end_estimate(known, universe, rules, calibration) == build_year_end_estimate(
        newer, universe, rules, calibration
    )
    missing = {**known, universe.peers[0].code: known[universe.peers[0].code][:-1]}
    with pytest.raises(ValueError, match=f"{universe.peers[0].code} {as_of}"):
        flat_projection_prices(missing, universe, as_of, [future])
