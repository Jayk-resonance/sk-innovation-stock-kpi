"""평가주가 · Peer 증감율 · 점수 산출.

    SK증감율    = SK_보정주가(평가일)   / SK_보정주가(기준일)   − 1
    Peer_i증감율 = Peer_i_보정주가(평가일) / Peer_i_보정주가(기준일) − 1
    Peer증감율   = 0.6 × 에화평균 + 0.4 × 배소평균
    x           = SK증감율 − Peer증감율                      (상대 증감율)
    평가주가     = SK_보정주가(평가일) × 1 / (1 − x)

기준 일치 원칙: SK 와 Peer 8사는 반드시 같은 윈도우·같은 산식을 쓴다.
`adjusted_prices()` 가 전 종목을 **한 번의 호출로** 계산하므로 어긋날 수가 없다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .schema import Bar, Universe
from .vwap import adjusted_price, apply_corporate_actions


@dataclass(frozen=True)
class Score:
    baseline: str
    anchor: float
    raw: float          # 클리핑 전 원값
    value: float        # 클리핑 후
    clipped: bool


@dataclass(frozen=True)
class Result:
    eval_date: date
    mode: str
    method: str
    subject_price: float                    # SK 거래량 보정 주가 (평가일)
    subject_change: float
    group_changes: dict[str, float]
    peer_change: float
    relative_change: float                  # x
    eval_price: float                       # 평가주가
    scores: dict[str, Score] = field(default_factory=dict)


def adjusted_prices(
    prices: dict[str, list[Bar]],
    universe: Universe,
    end: date,
    specs: list[str],
    method: str,
    corporate_actions: list[dict] | None = None,
) -> dict[str, float]:
    """전 종목의 거래량 보정 주가를 동일 조건으로 한 번에 계산한다."""
    actions = corporate_actions or []
    out = {}
    for ticker in universe.all_tickers:
        bars = prices.get(ticker.code)
        if not bars:
            raise ValueError(f"{ticker.name}({ticker.code}) 시세 데이터가 없다")
        out[ticker.code] = adjusted_price(
            apply_corporate_actions(bars, ticker.code, actions), end, specs, method
        )
    return out


def score_of(eval_price: float, anchor: float, scale: dict) -> tuple[float, float, bool]:
    """(원값, 클리핑 후, 클리핑 여부)."""
    base = scale["base_points"]
    low = anchor * (1 + scale["lower_bound_pct"])
    high = anchor * (1 + scale["upper_bound_pct"])
    if eval_price <= anchor:
        raw = base * (eval_price - low) / (anchor - low)
    else:
        raw = base + (scale["max_points"] - base) * (eval_price - anchor) / (high - anchor)
    if not scale.get("clip", True):
        return raw, raw, False
    value = min(max(raw, scale["min_points"]), scale["max_points"])
    return raw, value, value != raw


def price_for_points(scale: dict, anchor: float, points: float) -> float:
    """`score_of()` 의 역함수 — 목표 점수를 받으려면 평가주가가 얼마여야 하는가."""
    base, lo, hi = scale["base_points"], scale["lower_bound_pct"], scale["upper_bound_pct"]
    if points <= base:
        frac = (points - scale["min_points"]) / (base - scale["min_points"])
        return anchor * (1 + lo * (1 - frac))
    frac = (points - base) / (scale["max_points"] - base)
    return anchor * (1 + hi * frac)


def compose(change: dict[str, float], universe: Universe, subject_price: float) -> dict:
    """증감율 → 그룹평균 · Peer증감율 · 상대증감율 x · 평가주가.

    `evaluate()` 와 시나리오(민감도·Peer 기여도 분해)가 같은 공식을 쓰도록 분리했다.
    두 곳에 따로 적으면 반드시 어긋난다.
    """
    subject = universe.subject.code
    group_changes = {
        name: sum(change[t.code] for t in members) / len(members)
        for name, (_, members) in universe.groups.items()
    }
    peer = sum(weight * group_changes[name] for name, (weight, _) in universe.groups.items())
    relative = change[subject] - peer
    eval_price = subject_price / (1 - relative)
    return {
        "group_changes": group_changes,
        "peer_change": peer,
        "relative_change": relative,
        "eval_price": eval_price,
    }


def resolve_anchor(
    spec: dict,
    prices: dict[str, list[Bar]],
    universe: Universe,
    rules: dict,
    calibration: dict,
    method: str,
) -> float:
    """기준선 스펙(고정값 or 자체 산출)을 실제 앵커 가격으로 해석한다."""
    factor = float(calibration.get("calibration_factor", 1.0))
    if spec["source"] == "fixed":
        return float(spec["value"])
    actions = calibration.get("corporate_actions") or []
    return (
        adjusted_prices(
            prices, universe, rules["base_date"], rules["windows"][spec["mode"]], method, actions,
        )[universe.subject.code]
        * factor
    )


def evaluate(
    prices: dict[str, list[Bar]],
    universe: Universe,
    rules: dict,
    calibration: dict,
    eval_date: date,
    mode: str,
    method: str,
) -> Result:
    specs = rules["windows"][mode]
    actions = calibration.get("corporate_actions") or []
    factor = float(calibration.get("calibration_factor", 1.0))

    now = adjusted_prices(prices, universe, eval_date, specs, method, actions)
    base = adjusted_prices(prices, universe, rules["base_date"], specs, method, actions)
    change = {code: now[code] / base[code] - 1 for code in now}

    subject = universe.subject.code
    subject_price = now[subject] * factor
    comp = compose(change, universe, subject_price)

    scores = {}
    for key, spec in calibration["baselines"].items():
        # 기준일의 SK 보정주가를 앵커로 쓰는 버전은 앵커와 평가일 주가의 출처가
        # 같아져 PLAN.md §3 의 스케일 불일치가 상쇄된다.
        anchor = resolve_anchor(spec, prices, universe, rules, calibration, method)
        raw, value, clipped = score_of(comp["eval_price"], anchor, rules["score_scale"])
        scores[key] = Score(baseline=key, anchor=anchor, raw=raw, value=value, clipped=clipped)

    return Result(
        eval_date=eval_date,
        mode=mode,
        method=method,
        subject_price=subject_price,
        subject_change=change[subject],
        group_changes=comp["group_changes"],
        peer_change=comp["peer_change"],
        relative_change=comp["relative_change"],
        eval_price=comp["eval_price"],
        scores=scores,
    )
