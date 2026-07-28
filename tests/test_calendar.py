from datetime import date

import pytest

from core.calendar import minus_months, window_bounds


def test_windows_include_eval_date():
    """(가) 규칙: 평가일을 포함하는 달력 역산 (PLAN.md §7.2)."""
    eval_date = date(2026, 7, 15)
    assert window_bounds(eval_date, "2M") == (date(2026, 5, 16), eval_date)
    assert window_bounds(eval_date, "1M") == (date(2026, 6, 16), eval_date)
    assert window_bounds(eval_date, "1W") == (date(2026, 7, 9), eval_date)


def test_base_date_windows():
    base = date(2025, 12, 30)
    assert window_bounds(base, "2M") == (date(2025, 10, 31), base)
    assert window_bounds(base, "1M") == (date(2025, 12, 1), base)
    assert window_bounds(base, "1W") == (date(2025, 12, 24), base)


def test_one_week_is_seven_calendar_days():
    start, end = window_bounds(date(2026, 7, 15), "1W")
    assert (end - start).days + 1 == 7


def test_minus_months_clamps_to_month_end():
    assert minus_months(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert minus_months(date(2024, 3, 31), 1) == date(2024, 2, 29)  # 윤년
    assert minus_months(date(2026, 1, 15), 2) == date(2025, 11, 15)  # 연도 경계


def test_unknown_spec_rejected():
    with pytest.raises(ValueError, match="알 수 없는 윈도우"):
        window_bounds(date(2026, 7, 15), "5Y")


def test_free_window_combos_for_design_simulator():
    """PLAN.md §6 — 탭4는 2M/1M/1W 외 3M/6M/1D 등 자유 조합을 요구한다."""
    end = date(2026, 7, 15)
    assert window_bounds(end, "1D") == (end, end)
    assert window_bounds(end, "3M") == (date(2026, 4, 16), end)
    assert window_bounds(end, "6M") == (date(2026, 1, 16), end)
