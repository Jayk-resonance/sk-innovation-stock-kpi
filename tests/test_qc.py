from datetime import date, timedelta

from core.schema import Bar
from pipeline import qc

CODES = [f"{i:06d}" for i in range(9)]


def _series(days: list[date], close: int = 100) -> list[Bar]:
    return [Bar(d, close, 1000, close * 1000) for d in days]


def _weekdays(start: date, n: int) -> list[date]:
    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def test_trading_days_need_quorum():
    days = _weekdays(date(2026, 3, 2), 5)
    prices = {c: _series(days) for c in CODES[:4]}  # 4종목뿐 → 정족수 미달
    assert qc.trading_days(prices) == []
    prices[CODES[4]] = _series(days)
    assert qc.trading_days(prices) == days


def test_completeness_finds_single_ticker_gap():
    days = _weekdays(date(2026, 3, 2), 10)
    prices = {c: _series(days) for c in CODES}
    prices[CODES[0]] = _series(days[:5] + days[6:])  # 하루 누락
    findings = qc.check_completeness(prices)
    assert len(findings) == 1
    assert findings[0].code == CODES[0] and "결측 1일" in findings[0].message


def test_completeness_is_blind_to_universal_gap():
    """전 종목이 동시에 빠진 구간은 상호 대조로 잡히지 않는다 — 설계상의 한계."""
    days = _weekdays(date(2026, 3, 2), 10)
    with_gap = days[:4] + days[8:]
    prices = {c: _series(with_gap) for c in CODES}
    assert qc.check_completeness(prices) == []  # 못 잡는다
    assert qc.check_calendar_gaps(prices)       # 이쪽이 잡는다


def test_calendar_gap_levels():
    days = _weekdays(date(2026, 3, 2), 4)
    prices = {c: _series(days + [date(2026, 5, 4)]) for c in CODES}
    findings = qc.check_calendar_gaps(prices)
    assert len(findings) == 1 and findings[0].level == "error"
    assert "공백" in findings[0].message


def test_jumps_ignore_gap_boundaries():
    """공백을 사이에 둔 비교는 급변으로 오인하지 않는다."""
    before, after = date(2026, 1, 5), date(2026, 3, 5)
    prices = {CODES[0]: [Bar(before, 100, 1000, 100_000), Bar(after, 200, 1000, 200_000)]}
    assert qc.check_jumps(prices) == []

    consecutive = [Bar(date(2026, 3, 4), 100, 1000, 100_000), Bar(date(2026, 3, 5), 200, 1000, 200_000)]
    assert len(qc.check_jumps({CODES[0]: consecutive})) == 1


def test_share_change_detected_above_threshold():
    series = {CODES[0]: [(date(2026, 3, 4), 100_000_000), (date(2026, 3, 5), 110_000_000)]}
    findings = qc.check_share_changes(series)
    assert len(findings) == 1 and findings[0].level == "error"
    assert "발행주식수 변동" in findings[0].message


def test_share_noise_below_threshold_ignored():
    """시총 반올림에서 오는 미세 변동(±0.0003%)은 무시된다."""
    series = {CODES[0]: [(date(2026, 3, 4), 100_000_000), (date(2026, 3, 5), 100_000_300)]}
    assert qc.check_share_changes(series) == []


def test_zero_volume_flagged():
    prices = {CODES[0]: [Bar(date(2026, 3, 4), 100, 0, 0)]}
    findings = qc.check_values(prices)
    assert len(findings) == 1 and "거래정지" in findings[0].message


def test_window_coverage_reports_empty_window(prices, universe):
    """평가일 윈도우가 비면 산출 전에 걸러진다."""
    findings = qc.check_window_coverage(prices, universe, date(2025, 3, 1), ["2M"])
    assert len(findings) == 9


def test_real_data_has_no_missing_ticker_days(prices, universe):
    """실 데이터: 도출된 거래일 기준 종목별 결측 0."""
    assert qc.check_universe(prices, universe) == []
    assert qc.check_completeness(prices) == []
