"""정합성 검사 (QC 게이트).

거래일 캘린더는 **종목 간 상호 대조로 도출한다.** 외부 휴장일 파일에 의존하면
그 파일이 낡는 순간 조용히 틀리기 때문이다. 9종목 중 다수가 거래한 날은
거래일이고, 그날 빠진 종목이 있으면 그것이 결측이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from core.schema import Bar, Universe

QUORUM = 5              # 이 수 이상이 거래했으면 거래일로 본다
JUMP_THRESHOLD = 0.30   # 전일 대비 종가 변동 경보 기준
SHARE_THRESHOLD = 0.001  # 상장주식수 변동 감지 기준 (0.1%)
GAP_HOLIDAY_DAYS = 5     # 이 이상이면 연휴 여부 확인
GAP_ERROR_DAYS = 10      # 이 이상이면 수집 공백으로 단정. 국내 최장 연휴보다 길다


@dataclass
class Finding:
    level: str          # "error" | "warn"
    code: str
    message: str

    def __str__(self) -> str:
        mark = "✗" if self.level == "error" else "!"
        return f"  {mark} [{self.code}] {self.message}"


def trading_days(prices: dict[str, list[Bar]], quorum: int = QUORUM) -> list[date]:
    counts: dict[date, int] = {}
    for bars in prices.values():
        for bar in bars:
            counts[bar.day] = counts.get(bar.day, 0) + 1
    return sorted(d for d, n in counts.items() if n >= quorum)


def check_universe(prices: dict[str, list[Bar]], universe: Universe) -> list[Finding]:
    expected = {t.code for t in universe.all_tickers}
    return [
        Finding("error", code, "시세 데이터가 아예 없다")
        for code in sorted(expected - set(prices))
    ]


def check_completeness(
    prices: dict[str, list[Bar]], start: date | None = None, end: date | None = None
) -> list[Finding]:
    """거래일 대비 종목별 결측을 찾는다."""
    days = [d for d in trading_days(prices) if (not start or d >= start) and (not end or d <= end)]
    if not days:
        return [Finding("error", "-", "거래일을 하나도 도출하지 못했다")]
    window = set(days)
    findings = []
    for code, bars in sorted(prices.items()):
        missing = sorted(window - {b.day for b in bars})
        if missing:
            shown = ", ".join(str(d) for d in missing[:5])
            more = f" 외 {len(missing) - 5}일" if len(missing) > 5 else ""
            findings.append(Finding("error", code, f"결측 {len(missing)}일: {shown}{more}"))
    return findings


def check_values(prices: dict[str, list[Bar]]) -> list[Finding]:
    findings = []
    for code, bars in sorted(prices.items()):
        for bar in bars:
            if bar.volume == 0:
                findings.append(Finding("warn", code, f"{bar.day} 거래량 0 (거래정지 의심)"))
            if bar.trading_value == 0 and bar.volume > 0:
                findings.append(Finding("error", code, f"{bar.day} 거래대금만 0"))
    return findings


def check_calendar_gaps(prices: dict[str, list[Bar]]) -> list[Finding]:
    """전 종목이 동시에 비어 있는 구간을 찾는다.

    `check_completeness()` 는 종목 간 상호 대조 방식이라 **9종목이 모두 없는 구간은
    원리적으로 탐지하지 못한다.** 거래일 자체가 도출되지 않기 때문이다.
    그 사각지대를 메우는 검사다. 국내 최장 연휴(설·추석)를 넘는 공백만 오류로 단정한다.
    """
    days = trading_days(prices)
    findings = []
    for prev, cur in zip(days, days[1:]):
        gap = (cur - prev).days
        if gap > GAP_ERROR_DAYS:
            findings.append(
                Finding("error", "-", f"{prev} ~ {cur} 사이 {gap}일 공백 — 전 종목 데이터 없음")
            )
        elif gap > GAP_HOLIDAY_DAYS:
            findings.append(Finding("warn", "-", f"{prev} ~ {cur} 사이 {gap}일 공백 — 연휴 여부 확인"))
    return findings


def check_jumps(prices: dict[str, list[Bar]], threshold: float = JUMP_THRESHOLD) -> list[Finding]:
    """전일 대비 급변. 권리락·액면분할이면 여기서 먼저 걸린다.

    **인접 거래일끼리만 비교한다.** 데이터 공백을 사이에 두고 비교하면
    수주간의 누적 변동이 하루 급변으로 오인된다.
    """
    findings = []
    for code, bars in sorted(prices.items()):
        for prev, cur in zip(bars, bars[1:]):
            if (cur.day - prev.day).days > GAP_HOLIDAY_DAYS:
                continue  # 연휴·공백 구간. check_calendar_gaps 가 따로 잡는다
            move = cur.close / prev.close - 1
            if abs(move) > threshold:
                findings.append(
                    Finding("warn", code, f"{cur.day} 종가 {move:+.1%} 급변 — 권리락 여부 확인")
                )
    return findings


def check_share_changes(
    shares: dict[str, list[tuple[date, int]]], threshold: float = SHARE_THRESHOLD
) -> list[Finding]:
    """상장주식수 변동 = 유상증자·자사주 소각 등 (PLAN.md §5.2).

    시가총액÷주가 역산의 정밀도는 ±0.0003% 이므로 0.1% 기준은 충분히 안전하다.
    """
    findings = []
    for code, series in sorted(shares.items()):
        for (_, prev), (day, cur) in zip(series, series[1:]):
            if prev and abs(cur / prev - 1) > threshold:
                findings.append(
                    Finding(
                        "error", code,
                        f"{day} 상장주식수 {prev:,}→{cur:,} ({cur / prev - 1:+.2%}) "
                        f"— 발행주식수 변동 이벤트. DART 확인 후 조정계수 등록 필요",
                    )
                )
    return findings


def check_window_coverage(
    prices: dict[str, list[Bar]], universe: Universe, eval_date: date, specs: list[str]
) -> list[Finding]:
    """평가일 산출에 필요한 모든 윈도우가 채워져 있는가."""
    from core.calendar import window_bounds

    findings = []
    for ticker in universe.all_tickers:
        bars = prices.get(ticker.code, [])
        for spec in specs:
            start, end = window_bounds(eval_date, spec)
            if not [b for b in bars if start <= b.day <= end]:
                findings.append(
                    Finding("error", ticker.code, f"{eval_date} {spec} 윈도우({start}~{end}) 비어 있다")
                )
    return findings


def run_all(
    prices: dict[str, list[Bar]],
    universe: Universe,
    shares: dict[str, list[tuple[date, int]]] | None = None,
    start: date | None = None,
) -> list[Finding]:
    findings = check_universe(prices, universe)
    if findings:
        return findings  # 종목이 통째로 없으면 나머지 검사는 의미가 없다
    findings += check_completeness(prices, start=start)
    findings += check_calendar_gaps(prices)
    findings += check_values(prices)
    findings += check_jumps(prices)
    if shares:
        findings += check_share_changes(shares)
    return findings
