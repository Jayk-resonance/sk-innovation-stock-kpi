"""거래량 보정 주가 계산.

두 산식을 모두 지원한다 (PLAN.md §2 — 두 방식은 매일 다르나 2개월 누적 시
차이가 ±0.3% 이내로 수렴하고, 점수 영향은 0.5~0.9점이다).

    A: Σ거래대금 / Σ거래량             (체결 기준)
    B: Σ(종가 × 거래량) / Σ거래량       (사내 기존 방식)
"""
from __future__ import annotations

from datetime import date

from .calendar import window_bounds
from .schema import Bar

METHODS = ("A", "B")


def slice_window(bars: list[Bar], start: date, end: date) -> list[Bar]:
    return [b for b in bars if start <= b.day <= end]


def slice_spec_window(bars: list[Bar], end: date, spec: str) -> list[Bar]:
    """평가 스펙에 해당하는 봉.

    주 단위는 달력 7일이 아니라 주당 최근 5거래일을 사용한다. 월·일 단위는
    기존 달력 역산 경계를 그대로 유지한다.
    """
    normalized = spec.upper()
    if normalized.endswith("W") and normalized[:-1].isdigit():
        count = int(normalized[:-1]) * 5
        return [bar for bar in bars if bar.day <= end][-count:]
    return slice_window(bars, *window_bounds(end, normalized))


def vwap(bars: list[Bar], method: str) -> float:
    """윈도우 내 거래량가중평균주가."""
    if method not in METHODS:
        raise ValueError(f"알 수 없는 산식: {method!r} (가능: {METHODS})")
    if not bars:
        raise ValueError("빈 윈도우로는 VWAP 을 계산할 수 없다")
    volume = sum(b.volume for b in bars)
    if volume <= 0:
        raise ValueError(f"윈도우 거래량이 0이다 ({bars[0].day}~{bars[-1].day})")
    if method == "A":
        return sum(b.trading_value for b in bars) / volume
    return sum(b.close * b.volume for b in bars) / volume


def apply_corporate_actions(bars: list[Bar], code: str, actions: list[dict]) -> list[Bar]:
    """발행주식수 변동 이벤트의 가격 조정계수를 소급 적용한다.

    effective_date **이전** 봉의 가격측(종가·거래대금)에 factor 를 곱한다.
    거래량은 건드리지 않는다 — VWAP 은 가격측 스케일만 따라가므로 결과가 동일하다.

    자동 판정하지 않는다. calibration.yaml 에 사람이 등록한 것만 적용된다.
    """
    relevant = [a for a in actions if a["code"] == code]
    if not relevant:
        return bars
    adjusted = []
    for bar in bars:
        factor = 1.0
        for action in relevant:
            if bar.day < action["effective_date"]:
                factor *= float(action["factor"])
        adjusted.append(
            bar
            if factor == 1.0
            else Bar(
                day=bar.day,
                close=round(bar.close * factor),
                volume=bar.volume,
                trading_value=round(bar.trading_value * factor),
            )
        )
    return adjusted


def adjusted_price(bars: list[Bar], end: date, specs: list[str], method: str) -> float:
    """거래량 보정 주가.

    specs 가 1개면 그 윈도우의 VWAP, 여러 개면 각 VWAP 의 산술평균이다.
    (잠정 = ["2M"], 최종 = ["2M", "1M", "1W"]). 주 단위는 최근
    5거래일, 월 단위는 기존 달력 역산 경계를 사용한다.
    """
    values = [vwap(slice_spec_window(bars, end, s), method) for s in specs]
    return sum(values) / len(values)
