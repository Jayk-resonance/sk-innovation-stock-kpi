"""시뮬레이션 엔진 — 사이트 탭3(Case 시뮬레이션)·탭2 추가 기능이 쓰는 계산.

`evaluate()` 가 하는 "한 번 계산"을 여러 각도로 반복하거나 뒤집는 함수들이다.
공식 자체는 여기서 새로 적지 않는다 — `compose()`/`score_of()`/`resolve_anchor()`
(core/evaluate.py)를 그대로 재사용해, 평가 결과와 시나리오가 항상 같은 공식을 쓴다.
"""
from __future__ import annotations

from datetime import date, timedelta

from .calendar import minus_months, window_bounds
from .evaluate import adjusted_prices, compose, evaluate, price_for_points, resolve_anchor, score_of
from .schema import Bar, Universe


def score_matrix(prices, universe: Universe, rules: dict, calibration: dict, eval_date: date) -> list[dict]:
    """최종 평가 방식으로 계산한 기준가격별 점수 비교."""
    mode = "최종"
    method = rules["vwap_primary"]
    result = evaluate(prices, universe, rules, calibration, eval_date, mode, method)
    return [
        {
            "mode": mode,
            "method": method,
            "baseline": key,
            "anchor": round(score.anchor, 2),
            "raw": round(score.raw, 4),
            "value": round(score.value, 2),
            "clipped": score.clipped,
        }
        for key, score in result.scores.items()
    ]


def _base_inputs(prices, universe, rules, calibration, eval_date, mode, method):
    specs = rules["windows"][mode]
    actions = calibration.get("corporate_actions") or []
    factor = float(calibration.get("calibration_factor", 1.0))
    now = adjusted_prices(prices, universe, eval_date, specs, method, actions)
    base = adjusted_prices(prices, universe, rules["base_date"], specs, method, actions)
    change = {code: now[code] / base[code] - 1 for code in now}
    return now, base, change, factor


def peer_waterfall(
    prices, universe: Universe, rules: dict, calibration: dict,
    eval_date: date, mode: str, method: str, baseline_key: str = "V3",
) -> list[dict]:
    """"내 점수를 어느 Peer가 얼마나 깎았는가" — 순차 기여도 분해.

    출발점(step 0)은 "Peer 전원 변동 없음" 일 때의 점수, 즉 SK 단독 성과만 반영한
    점수다. 거기서 종목을 하나씩(에화 → 배소 순) 실제 증감율로 되돌리며 점수가
    어떻게 바뀌는지 누적한다. 단계 합이 항상 실제 점수와 정확히 일치한다(재구성).
    순차 방식이라 종목 순서를 바꾸면 기여도 배분이 달라질 수 있다 — 다만 마지막
    합계(재구성 결과)는 순서와 무관하게 항상 실제 점수와 같다.
    """
    now, base, change, factor = _base_inputs(prices, universe, rules, calibration, eval_date, mode, method)
    subject = universe.subject.code
    subject_price = now[subject] * factor
    anchor = resolve_anchor(calibration["baselines"][baseline_key], prices, universe, rules, calibration, method)
    scale = rules["score_scale"]

    def score_at(chg):
        comp = compose(chg, universe, subject_price)
        _, value, _ = score_of(comp["eval_price"], anchor, scale)
        return value

    flat = dict(change)
    for peer in universe.peers:
        flat[peer.code] = 0.0
    steps = [{"name": "Peer 변동 없음 (SK 단독 성과)", "group": None, "score": round(score_at(flat), 2)}]

    running = dict(flat)
    for name, (_, members) in universe.groups.items():
        for peer in members:
            running = dict(running)
            running[peer.code] = change[peer.code]
            steps.append({"name": peer.name, "group": name, "score": round(score_at(running), 2)})

    for i in range(1, len(steps)):
        steps[i]["delta"] = round(steps[i]["score"] - steps[i - 1]["score"], 2)
    return steps


def sensitivity_table(
    prices, universe: Universe, rules: dict, calibration: dict,
    eval_date: date, mode: str, method: str, baseline_key: str = "V3", bump: float = 0.01,
) -> dict:
    """SK ±1% / Peer그룹 ±1% 변동 시 점수 변화량."""
    now, base, change, factor = _base_inputs(prices, universe, rules, calibration, eval_date, mode, method)
    subject = universe.subject.code
    anchor = resolve_anchor(calibration["baselines"][baseline_key], prices, universe, rules, calibration, method)
    scale = rules["score_scale"]

    def score_with(chg, subject_price):
        comp = compose(chg, universe, subject_price)
        _, value, _ = score_of(comp["eval_price"], anchor, scale)
        return value

    base_score = score_with(change, now[subject] * factor)
    rows = []
    for sign, label in ((1, "+1%p"), (-1, "-1%p")):
        chg = dict(change)
        chg[subject] = change[subject] + sign * bump
        subject_price = now[subject] * (1 + sign * bump) * factor
        s = score_with(chg, subject_price)
        rows.append({"target": "SK이노베이션", "shift": label, "score": round(s, 2),
                     "delta": round(s - base_score, 2)})
    for name, (_, members) in universe.groups.items():
        for sign, label in ((1, "+1%p"), (-1, "-1%p")):
            chg = dict(change)
            for peer in members:
                chg[peer.code] = change[peer.code] + sign * bump
            s = score_with(chg, now[subject] * factor)
            rows.append({"target": f"{name} 그룹", "shift": label, "score": round(s, 2),
                         "delta": round(s - base_score, 2)})
    return {"base_score": round(base_score, 2), "bump": bump, "rows": rows}


def target_price(
    prices, universe: Universe, rules: dict, calibration: dict,
    eval_date: date, mode: str, method: str, target_points: float, baseline_key: str = "V3",
) -> dict:
    """"target_points 점을 받으려면 SK 주가가 얼마여야 하는가" — Peer 현재가 고정.

    x = SK증감율 c − Peer증감율 P(고정) 이고 평가주가 = SK보정주가×(1+c) / (1−c+P)
    이므로, 목표 평가주가를 알면 c 에 대해 정확히 풀린다(유리식 1차 방정식).
    """
    now, base, change, factor = _base_inputs(prices, universe, rules, calibration, eval_date, mode, method)
    subject = universe.subject.code
    comp = compose(change, universe, now[subject] * factor)
    peer_change = comp["peer_change"]
    anchor = resolve_anchor(calibration["baselines"][baseline_key], prices, universe, rules, calibration, method)
    target_eval_price = price_for_points(rules["score_scale"], anchor, target_points)

    k = base[subject] * factor
    c = (target_eval_price * (1 + peer_change) - k) / (k + target_eval_price)
    needed_vwap = k * (1 + c)
    return {
        "target_points": target_points,
        "target_eval_price": round(target_eval_price, 2),
        "needed_vwap": round(needed_vwap, 2),
        "needed_change_from_base": round(c, 6),
        "current_vwap": round(now[subject] * factor, 2),
        "current_change_from_base": round(change[subject], 6),
    }


def _synthetic_extend(bars: list[Bar], upto: date, daily_return: float) -> list[Bar]:
    """실제 마지막 봉 이후 `upto` 까지, 매일 daily_return 만큼 복리 상승하는 가상 봉을 잇는다.

    "잔여기간 경로 시나리오" 전용 — 실제로 아직 일어나지 않은 미래를 가정하므로
    거래량은 알 수 없다. 최근 20거래일 평균 거래량으로 고정한다(추세 판단용 근사치).
    휴장일은 주말만 근사로 걸러낸다 — 실제 공휴일 캘린더는 반영하지 않는다.
    """
    last = bars[-1]
    recent = bars[-20:]
    volume = round(sum(b.volume for b in recent) / len(recent))
    out = list(bars)
    day, price = last.day, float(last.close)
    while day < upto:
        day = day + timedelta(days=1)
        if day.weekday() >= 5:
            continue
        price *= 1 + daily_return
        close = round(price)
        out.append(Bar(day=day, close=close, volume=volume, trading_value=close * volume))
    return out


def remaining_path_scenarios(
    prices, universe: Universe, rules: dict, calibration: dict,
    as_of: date, horizon_months: int, method: str = "B", baseline_key: str = "V3",
    annual_rates: tuple[float, ...] = (0.20, 0.0, -0.20),
) -> dict:
    """평가일까지 남은 기간 동안 SK 주가가 상승/보합/하락하면 점수가 어떻게 되는가.

    Peer 는 현재 수준에서 그대로 고정한다고 가정한다(등락 예측은 이 기능의 범위 밖).
    VWAP 은 과거 누적이라 평가일에 가까워질수록 이미 확정된 구간이 늘어나
    남은 변동 여지가 줄어든다 — `lock_in_pct` 가 그 비율이다.
    """
    horizon = minus_months(as_of, -horizon_months)
    labels = {0.20: "상승 시나리오 (연 +20%)", 0.0: "보합", -0.20: "하락 시나리오 (연 −20%)"}
    subject_code = universe.subject.code
    scenarios = []
    for annual in annual_rates:
        daily_rate = (1 + annual) ** (1 / 252) - 1
        ext = dict(prices)
        ext[subject_code] = _synthetic_extend(prices[subject_code], horizon, daily_rate)
        for peer in universe.peers:
            ext[peer.code] = _synthetic_extend(prices[peer.code], horizon, 0.0)
        result = evaluate(ext, universe, rules, calibration, horizon, "최종", method)
        score = result.scores[baseline_key]
        scenarios.append({
            "label": labels.get(annual, f"{annual:+.0%}"), "annual_rate": annual,
            "eval_price": round(result.eval_price, 2),
            "raw": round(score.raw, 2), "value": round(score.value, 2),
        })

    windows = [window_bounds(horizon, spec)[0] for spec in rules["windows"]["최종"]]
    window_start = min(windows)
    lock_in = []
    for start in windows:
        total_days = (horizon - start).days + 1
        realized_days = max(0, min(total_days, (as_of - start).days + 1))
        lock_in.append(realized_days / total_days)
    return {
        "horizon": horizon.isoformat(), "horizon_months": horizon_months,
        "window_start": window_start.isoformat(),
        "lock_in_pct": round(sum(lock_in) / len(lock_in), 4),
        "scenarios": scenarios,
    }


def score_timeseries(
    prices, universe: Universe, rules: dict, calibration: dict,
    days: list[date], method: str, mode: str = "잠정", baseline_key: str = "V3",
) -> list[dict]:
    """일별 "그날 평가했다면" 점수 추이. 윈도우가 걸치는 초반 며칠은 데이터가 얇아
    변동폭이 커 보일 수 있다 — 실제 평가는 이 중 특정일만 유효하다."""
    out = []
    for d in days:
        if d < rules["base_date"]:
            continue
        result = evaluate(prices, universe, rules, calibration, d, mode, method)
        score = result.scores[baseline_key]
        out.append({
            "date": d.isoformat(),
            "value": round(score.value, 2),
            "raw": round(score.raw, 2),
            "subject_price": round(result.subject_price, 2),
            "subject_change": round(result.subject_change, 6),
            "peer_change": round(result.peer_change, 6),
            "eval_price": round(result.eval_price, 2),
        })
    return out
