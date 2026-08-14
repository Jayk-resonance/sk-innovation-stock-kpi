"""윈도우 경계 산출.

경계 규칙은 (가) — **평가일을 포함하는 달력 역산** (PLAN.md §7.2 확정).

    2M: 평가일 −2개월 +1일 ~ 평가일
    1M: 평가일 −1개월 +1일 ~ 평가일
    1W: 이 모듈의 일반 달력 경계는 평가일 −7일 +1일 ~ 평가일

실제 평가에서 주 단위 스펙은 ``core.vwap.slice_spec_window``가 최근 5거래일로
해석한다. 1M·2M 등 월 단위는 이 모듈의 달력 역산 경계를 그대로 사용한다.

스펙 표기는 `{n}{D|W|M}` 일반형이다 (예: "1D", "3M", "6M") — 탭4 설계 시뮬레이터가
2M/1M/1W 외의 자유 윈도우 조합을 요구하기 때문이다(PLAN.md §6).
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta

SPEC_RE = re.compile(r"^(\d+)([DWM])$")
SPECS = ("2M", "1M", "1W")   # 기존 확정 스펙 (하위 호환용 참고 상수)


def minus_months(day: date, months: int) -> date:
    """달력 기준 n개월 전. 말일은 해당 월의 말일로 맞춘다 (3/31 −1개월 → 2/28)."""
    total = day.year * 12 + (day.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def window_bounds(end: date, spec: str) -> tuple[date, date]:
    """윈도우 [시작, 끝] 을 반환한다. 양 끝 모두 포함."""
    m = SPEC_RE.match(spec.upper())
    if not m:
        raise ValueError(f"알 수 없는 윈도우: {spec!r} (형식: {{n}}{{D|W|M}}, 예: 2M, 1W, 3M)")
    n, unit = int(m.group(1)), m.group(2)
    if unit == "D":
        start = end - timedelta(days=n - 1)
    elif unit == "W":
        start = end - timedelta(days=n * 7 - 1)
    else:  # "M"
        start = minus_months(end, n) + timedelta(days=1)
    return start, end
