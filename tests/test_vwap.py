from datetime import date

import pytest

from core.schema import Bar
from core.vwap import adjusted_price, apply_corporate_actions, slice_window, vwap

SK = "096770"


def _bar(day: int, close: int, volume: int, trading_value: int) -> Bar:
    return Bar(date(2026, 7, day), close, volume, trading_value)


def test_two_methods_differ_by_construction():
    """종가와 당일 실제 VWAP 이 다르면 두 산식은 다른 값을 낸다 (PLAN.md §2)."""
    bars = [
        _bar(13, close=100, volume=10, trading_value=1050),  # 일 VWAP 105
        _bar(14, close=200, volume=30, trading_value=5700),  # 일 VWAP 190
    ]
    assert vwap(bars, "A") == (1050 + 5700) / 40  # 168.75
    assert vwap(bars, "B") == (100 * 10 + 200 * 30) / 40  # 175.0


def test_methods_agree_when_close_equals_daily_vwap():
    bars = [_bar(13, 100, 10, 1000), _bar(14, 200, 30, 6000)]
    assert vwap(bars, "A") == vwap(bars, "B")


def test_empty_window_raises():
    with pytest.raises(ValueError, match="빈 윈도우"):
        vwap([], "A")


def test_zero_volume_raises():
    with pytest.raises(ValueError, match="거래량이 0"):
        vwap([_bar(13, 100, 0, 0)], "A")


def test_unknown_method_raises():
    with pytest.raises(ValueError, match="알 수 없는 산식"):
        vwap([_bar(13, 100, 10, 1000)], "C")


def test_slice_window_is_inclusive():
    bars = [_bar(d, 100, 10, 1000) for d in (13, 14, 15, 16)]
    got = slice_window(bars, date(2026, 7, 14), date(2026, 7, 15))
    assert [b.day.day for b in got] == [14, 15]


def test_corporate_action_scales_price_side_only():
    bars = [_bar(13, 100, 10, 1000), _bar(15, 100, 10, 1000)]
    actions = [{"code": SK, "effective_date": date(2026, 7, 14), "factor": 0.5}]
    out = apply_corporate_actions(bars, SK, actions)
    assert (out[0].close, out[0].trading_value, out[0].volume) == (50, 500, 10)
    assert (out[1].close, out[1].trading_value, out[1].volume) == (100, 1000, 10)


def test_corporate_action_ignores_other_codes():
    bars = [_bar(13, 100, 10, 1000)]
    actions = [{"code": "051910", "effective_date": date(2026, 7, 14), "factor": 0.5}]
    assert apply_corporate_actions(bars, SK, actions) == bars


def test_adjusted_price_averages_multiple_windows(prices):
    """최종평가는 세 윈도우 VWAP 의 산술평균이다."""
    bars, end = prices[SK], date(2026, 7, 15)
    parts = [
        adjusted_price(bars, end, [spec], "B") for spec in ("2M", "1M", "1W")
    ]
    combined = adjusted_price(bars, end, ["2M", "1M", "1W"], "B")
    assert combined == pytest.approx(sum(parts) / 3)


def test_real_data_base_window_vwap(prices):
    """기준일 2개월 VWAP — 회귀 고정 (KIS 실 데이터)."""
    base = date(2025, 12, 30)
    assert adjusted_price(prices[SK], base, ["2M"], "A") == pytest.approx(116_905, abs=1)
    assert adjusted_price(prices[SK], base, ["2M"], "B") == pytest.approx(116_576, abs=1)
