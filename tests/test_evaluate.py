from datetime import date

import pytest

from core.evaluate import adjusted_prices, evaluate, score_of

SK = "096770"
SCALE = {
    "base_points": 40,
    "min_points": 0,
    "max_points": 100,
    "lower_bound_pct": -0.15,
    "upper_bound_pct": 0.15,
    "clip": True,
}


# ── 점수 환산 ────────────────────────────────────────────────────────────

def test_score_anchors():
    anchor = 113_109
    assert score_of(anchor, anchor, SCALE)[1] == pytest.approx(40)
    assert score_of(anchor * 0.85, anchor, SCALE)[1] == pytest.approx(0)
    assert score_of(anchor * 1.15, anchor, SCALE)[1] == pytest.approx(100)


def test_score_is_linear_within_each_segment():
    anchor = 100_000
    assert score_of(anchor * 0.925, anchor, SCALE)[1] == pytest.approx(20)  # 하단 중간
    assert score_of(anchor * 1.075, anchor, SCALE)[1] == pytest.approx(70)  # 상단 중간


def test_clipping_preserves_raw_value():
    anchor = 100_000
    raw, value, clipped = score_of(anchor * 0.80, anchor, SCALE)
    assert raw < 0 and value == 0 and clipped is True

    raw, value, clipped = score_of(anchor * 1.20, anchor, SCALE)
    assert raw > 100 and value == 100 and clipped is True


def test_clip_can_be_disabled():
    raw, value, clipped = score_of(80_000, 100_000, {**SCALE, "clip": False})
    assert raw == value < 0 and clipped is False


# ── 항등식 ───────────────────────────────────────────────────────────────

def test_base_date_identity(prices, universe, rules, calibration):
    """기준일에는 x=0 이므로 평가주가 = SK 거래량보정주가."""
    for mode in ("잠정", "최종"):
        r = evaluate(prices, universe, rules, calibration, rules["base_date"], mode, "B")
        assert r.relative_change == pytest.approx(0, abs=1e-12)
        assert r.eval_price == pytest.approx(r.subject_price)


def test_computed_baseline_scores_exactly_40(prices, universe, rules, calibration):
    """자체 산출 V1은 앵커와 평가주가의 출처가 같아 기준일에 정확히 40점이다."""
    r = evaluate(prices, universe, rules, calibration, rules["base_date"], "잠정", "B")
    assert r.scores["V1"].value == pytest.approx(40.0)


def test_final_target_matches_base_windows(prices, universe, rules, calibration):
    """최종 방식의 SK·Peer 기준기간은 109,922원 산출기간과 같아야 한다."""
    r = evaluate(prices, universe, rules, calibration, rules["base_date"], "최종", "B")
    assert r.scores["V2"].anchor == 109_922
    assert r.subject_price == pytest.approx(109_922, abs=1)
    assert r.scores["V2"].value == pytest.approx(40, abs=0.01)


def test_official_baseline_is_biased_at_base_date(prices, universe, rules, calibration):
    """⚠️ V3(113,109원)는 기준일에 40점이 나오지 않는다 — PLAN.md §3 미해결 리스크.

    편향의 부호가 평가 방식에 따라 뒤집힌다는 점이 중요하다.
    113,109원이 2개월 VWAP 과 3종 평균 사이에 있다는 뜻이며,
    윈도우 정의 차이가 원인일 가능성을 시사한다.
    """
    provisional = evaluate(prices, universe, rules, calibration, rules["base_date"], "잠정", "B")
    final = evaluate(prices, universe, rules, calibration, rules["base_date"], "최종", "B")
    assert provisional.scores["V3"].value == pytest.approx(52.26, abs=0.05)  # +12.3점
    assert final.scores["V3"].value == pytest.approx(32.49, abs=0.05)  # −7.5점


# ── 기준 일치 원칙 ───────────────────────────────────────────────────────

def test_all_tickers_computed_in_one_call(prices, universe, rules):
    """SK 와 Peer 8사는 한 번의 호출로 동일 조건 계산된다 — 구조적으로 어긋날 수 없다."""
    out = adjusted_prices(prices, universe, date(2026, 7, 15), rules["windows"]["잠정"], "B")
    assert set(out) == {t.code for t in universe.all_tickers}
    assert len(out) == 9


def test_missing_ticker_raises_loudly(prices, universe, rules):
    partial = {k: v for k, v in prices.items() if k != "051910"}
    with pytest.raises(ValueError, match="시세 데이터가 없다"):
        adjusted_prices(partial, universe, date(2026, 7, 15), rules["windows"]["잠정"], "B")


def test_insufficient_history_raises(prices, universe, rules, calibration):
    """데이터가 없는 평가일은 조용히 넘어가지 않고 실패해야 한다."""
    with pytest.raises(ValueError, match="빈 윈도우"):
        evaluate(prices, universe, rules, calibration, date(2025, 3, 1), "잠정", "B")


def test_2026_q1_provisional_regression(prices, universe, rules, calibration):
    """2026 1분기 잠정평가 (4/16)."""
    r = evaluate(prices, universe, rules, calibration, date(2026, 4, 16), "잠정", "B")
    assert r.relative_change == pytest.approx(-0.1446, abs=1e-4)
    assert r.eval_price == pytest.approx(106_219, abs=1)
    assert r.scores["V3"].value == pytest.approx(23.76, abs=0.02)
    assert r.scores["V3"].clipped is False


# ── 실 데이터 회귀 ───────────────────────────────────────────────────────

def test_2026_h1_provisional_regression(prices, universe, rules, calibration):
    """2026 상반기 잠정평가 (7/15) — 검증 완료된 실측값 고정."""
    r = evaluate(prices, universe, rules, calibration, date(2026, 7, 15), "잠정", "B")
    assert r.subject_change == pytest.approx(-0.0696, abs=1e-4)
    assert r.group_changes["에화"] == pytest.approx(0.0774, abs=1e-4)
    assert r.group_changes["배소"] == pytest.approx(0.1606, abs=1e-4)
    assert r.peer_change == pytest.approx(0.1107, abs=1e-4)
    assert r.relative_change == pytest.approx(-0.1803, abs=1e-4)
    assert r.eval_price == pytest.approx(91_896, abs=1)

    score = r.scores["V3"]
    assert score.raw == pytest.approx(-10.01, abs=0.02)
    assert score.value == 0.0
    assert score.clipped is True


def test_method_ab_gap_stays_under_one_point(prices, universe, rules, calibration):
    """산식 A/B 차이는 1점 미만이다 (PLAN.md §2)."""
    a = evaluate(prices, universe, rules, calibration, date(2026, 7, 15), "잠정", "A")
    b = evaluate(prices, universe, rules, calibration, date(2026, 7, 15), "잠정", "B")
    assert abs(a.scores["V3"].raw - b.scores["V3"].raw) < 1.0


def test_peer_weights_applied(prices, universe, rules, calibration):
    r = evaluate(prices, universe, rules, calibration, date(2026, 7, 15), "잠정", "B")
    expected = 0.6 * r.group_changes["에화"] + 0.4 * r.group_changes["배소"]
    assert r.peer_change == pytest.approx(expected)
