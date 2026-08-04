from datetime import date

from core.schema import Bar
from pipeline.verify import (
    MonthCheck,
    build_evidence_package,
    cross_check_monthly,
    verify_windows,
)


def _check(**kw) -> MonthCheck:
    base = dict(code="096770", month="2026-03", daily_volume=100, ref_volume=100,
                daily_value=1000, ref_value=1000, covered=True)
    return MonthCheck(**{**base, **kw})


def test_verdicts():
    assert _check().verdict == "일치"
    assert _check(daily_volume=90, daily_value=900).verdict == "결측"
    assert _check(daily_volume=110, daily_value=1100).verdict == "중복"


def test_partial_month_is_not_judged():
    """부분 수집한 달을 '결측'으로 단정하지 않는다."""
    partial = _check(covered=False, daily_volume=40, daily_value=400)
    assert partial.verdict == "검증불가(부분수집)"
    assert partial.exact is False


def test_full_month_matches_reference(prices):
    """실 데이터: 통째로 수집한 달은 원 단위로 일치한다."""
    checks = [c for c in cross_check_monthly(prices) if c.covered]
    assert checks, "검증 가능한 달이 하나도 없다"
    assert all(c.exact for c in checks)
    assert all(c.vwap_error == 0 for c in checks)


def test_every_month_is_fully_verified(prices):
    """백필 완료 후: 보유한 모든 달이 원 단위로 일치한다."""
    checks = cross_check_monthly(prices)
    assert len(checks) == 99  # 11개월 × 9종목
    assert all(c.covered and c.exact for c in checks)


def test_holiday_does_not_split_collection_runs(prices):
    """설 연휴(2026-02-14~18)를 수집 공백으로 오인하면 2월이 검증불가가 된다."""
    feb = [c for c in cross_check_monthly(prices) if c.month == "2026-02"]
    assert len(feb) == 9 and all(c.covered for c in feb)


def test_month_ending_on_holiday_counts_as_covered(prices):
    """2025-12-31 은 휴장이다. 달력 말일로 판정하면 완전 수집한 12월을 놓친다."""
    dec = [c for c in cross_check_monthly(prices) if c.month == "2025-12"]
    assert len(dec) == 9
    assert all(c.covered and c.exact for c in dec)


def test_cross_check_detects_injected_gap(prices):
    """일봉을 하나 빼면 그 달이 '결측'으로 잡힌다 — 실제 2026-05-26/27 사고와 같은 형태."""
    tampered = {c: list(b) for c, b in prices.items()}
    victim = [b for b in tampered["096770"] if b.day.strftime("%Y-%m") == "2026-06"][0]
    tampered["096770"] = [b for b in tampered["096770"] if b is not victim]
    june = [c for c in cross_check_monthly(tampered) if c.code == "096770" and c.month == "2026-06"]
    assert june[0].verdict == "결측"
    assert june[0].vwap_error is not None


def test_cross_check_detects_duplicate(prices):
    tampered = {c: list(b) for c, b in prices.items()}
    dup = [b for b in tampered["096770"] if b.day.strftime("%Y-%m") == "2026-06"][0]
    tampered["096770"] = sorted(tampered["096770"] + [Bar(dup.day, dup.close, dup.volume,
                                                         dup.trading_value)],
                                key=lambda b: b.day)
    june = [c for c in cross_check_monthly(tampered) if c.code == "096770" and c.month == "2026-06"]
    assert june[0].verdict == "중복"


def test_verify_windows_passes_for_both_evaluations(prices, universe, rules):
    for entry in rules["eval_dates"]:
        ok, checks = verify_windows(prices, universe, entry["date"],
                                    rules["windows"][entry["mode"]])
        assert ok, f"{entry['label']} 교차검증 실패"
        assert checks


def test_evidence_package_is_complete(prices, universe, rules, calibration, tmp_path):
    root = build_evidence_package(prices, universe, rules, calibration,
                                  date(2026, 7, 15), "잠정", "B", "테스트", out_dir=tmp_path)
    names = {f.name for f in root.iterdir()}
    assert names == {"00_SUMMARY.md", "01_raw_bars.csv", "02_vwap.csv",
                     "03_trace.csv", "04_cross_check.csv"}
    summary = (root / "00_SUMMARY.md").read_text(encoding="utf-8")
    assert "상대 증감율 x" in summary and "91,896원" in summary
    assert "교차검증: ✅" in summary  # 검증 상태를 요약 첫머리에 밝힌다


def test_evidence_trace_covers_every_ticker(prices, universe, rules, calibration, tmp_path):
    root = build_evidence_package(prices, universe, rules, calibration,
                                  date(2026, 7, 15), "잠정", "B", "테스트", out_dir=tmp_path)
    trace = (root / "03_trace.csv").read_text(encoding="utf-8")
    for ticker in universe.all_tickers:
        assert f"{ticker.name} 증감율" in trace
