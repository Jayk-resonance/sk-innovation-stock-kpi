"""계산 결과 → 사이트 데이터(JSON).

사이트는 계산하지 않는다. 여기서 만든 JSON을 읽어 그리기만 한다.
계산은 `core/` 한 곳에만 있어야 검증 결과가 사이트에도 그대로 적용된다.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import subprocess

from core.evaluate import adjusted_prices, evaluate, price_for_points
from core.scenarios import (
    peer_waterfall,
    remaining_path_scenarios,
    score_matrix,
    score_timeseries,
    sensitivity_table,
    target_price,
)
from core.schema import Bar, Universe
from pipeline.qc import GAP_ERROR_DAYS, check_calendar_gaps, trading_days
from pipeline.verify import cross_check_monthly

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DATA = REPO_ROOT / "docs" / "data"
TARGET_MARKS = (0, 40, 80, 100)
BASE_INDEX = 100.0
SPARK_POINTS = 40   # 표 스파크라인이 쓰는 최근 거래일 수


def _ticker_meta(universe: Universe) -> list[dict]:
    out = [{"code": universe.subject.code, "name": universe.subject.name,
            "group": "본사", "weight": None}]
    for group, (weight, members) in universe.groups.items():
        out += [{"code": t.code, "name": t.name, "group": group, "weight": weight}
                for t in members]
    return out


def _group_index(indexed: dict[str, list], universe: Universe) -> dict[str, list]:
    """그룹 구성원 지수의 산술평균. 한 종목이라도 비면 그날은 None."""
    out: dict[str, list] = {}
    for name, (_, members) in universe.groups.items():
        rows = [indexed[t.code] for t in members]
        out[name] = [
            None if any(v is None for v in day) else round(sum(day) / len(day), 2)
            for day in zip(*rows)
        ]
    return out


def build_history(prices: dict[str, list[Bar]], base_date: date,
                  universe: Universe | None = None) -> dict:
    """일별 종가와, 기준일=100 으로 정규화한 지수.

    결측일은 `null` 로 둔다. 선을 이어 그리면 없는 데이터를 있는 것처럼
    보이게 되므로, 사이트에서 끊어 그릴 수 있도록 구멍을 그대로 남긴다.
    """
    days = trading_days(prices)
    labels = [d.isoformat() for d in days]
    close: dict[str, list[float | None]] = {}
    indexed: dict[str, list[float | None]] = {}
    for code, bars in prices.items():
        by_day = {b.day: b.close for b in bars}
        anchor = by_day.get(base_date)
        close[code] = [by_day.get(d) for d in days]
        indexed[code] = (
            [None if by_day.get(d) is None else round(by_day[d] / anchor * BASE_INDEX, 2)
             for d in days]
            if anchor else [None] * len(days)
        )
    # 차트는 9개 시리즈를 그리지 않는다. 개별 Peer 색을 9개 만들면 서로
    # 구분되지 않고, KPI 가 실제로 재는 것도 개별사가 아니라 그룹이다
    # (가중치 60:40 이 그룹 단위). SK · 에화평균 · 배소평균 3개로 접는다.
    # 개별 종목 추세는 표의 스파크라인이 맡는다.
    # 수집 공백 구간은 날짜 항목 자체가 없다. 인접 인덱스를 선으로 이으면
    # 51일 공백이 하루 급변처럼 보이므로, 끊어야 할 위치를 따로 알려준다.
    # 임계값은 qc 와 같아야 한다. 더 짧게 잡으면 설·추석 연휴에서 선이 끊긴다.
    gap_after = [i for i, (a, b) in enumerate(zip(days, days[1:]))
                 if (b - a).days > GAP_ERROR_DAYS]
    payload = {"dates": labels, "close": close, "indexed": indexed, "gap_after": gap_after,
               "base_date": base_date.isoformat(), "base_index": BASE_INDEX}
    if universe:
        payload["subject"] = universe.subject.code
        payload["groups"] = _group_index(indexed, universe)
    return payload


def _score_marks(scale: dict, anchor: float) -> list[dict]:
    """점수 눈금(0·40·80·100)이 각각 어느 평가주가인지.

    상단 구간은 40점에서 100점까지 60점을 15% 에 걸쳐 나누므로
    80점은 앵커의 +10% 지점이다. 눈금을 화면에 박지 않고 여기서 계산해 넘긴다.
    """
    return [{"points": pt, "price": round(price_for_points(scale, anchor, pt), 2)}
            for pt in (scale["min_points"], scale["base_points"], 80, scale["max_points"])]


def _mode_detail(prices, universe, rules, calibration, eval_date, mode, method) -> dict:
    """한 평가시점·한 방식의 산출 전 과정.

    잠정과 최종을 나란히 놓고 어디서 갈라지는지 보려면 윈도우별 VWAP 까지
    필요하다. 화면에서 다시 계산하지 않도록 여기서 전부 펼쳐 넘긴다.
    """
    from core.vwap import adjusted_price, apply_corporate_actions

    specs = rules["windows"][mode]
    actions = calibration.get("corporate_actions") or []
    result = evaluate(prices, universe, rules, calibration, eval_date, mode, method)
    subject = universe.subject.code
    bars = apply_corporate_actions(prices[subject], subject, actions)

    def windows(anchor_date):
        return [{"spec": s, "vwap": round(adjusted_price(bars, anchor_date, [s], method), 2)}
                for s in specs]

    by_day = {b.day: b for b in prices[subject]}
    now = adjusted_prices(prices, universe, eval_date, specs, method, actions)
    base = adjusted_prices(prices, universe, rules["base_date"], specs, method, actions)

    groups = {}
    for name, (weight, members) in universe.groups.items():
        groups[name] = {
            "weight": weight,
            "average": round(result.group_changes[name], 6),
            "members": [{"name": t.name,
                         "change": round(now[t.code] / base[t.code] - 1, 6)}
                        for t in members],
        }

    return {
        **_result_json(result),
        "specs": specs,
        "subject_close": by_day[eval_date].close if eval_date in by_day else None,
        "windows_now": windows(eval_date),
        "windows_base": windows(rules["base_date"]),
        "subject_base_price": round(base[subject], 2),
        "groups": groups,
        "score_marks": {k: _score_marks(rules["score_scale"], s["anchor"])
                        for k, s in _result_json(result)["scores"].items()},
        # 목표 역산 · Peer 기여도 · 민감도는 공식 기준선(V3) 기준으로만 계산한다 —
        # 화면의 헤드라인 숫자와 같은 기준이어야 "왜 이 점수인가"에 답이 된다.
        "targets": {pt: target_price(prices, universe, rules, calibration, eval_date, mode, method, pt)
                    for pt in TARGET_MARKS},
        "waterfall": peer_waterfall(prices, universe, rules, calibration, eval_date, mode, method),
        "sensitivity": sensitivity_table(prices, universe, rules, calibration, eval_date, mode, method),
    }


def _result_json(result) -> dict:
    return {
        "mode": result.mode,
        "method": result.method,
        "eval_date": result.eval_date.isoformat(),
        "subject_price": round(result.subject_price, 2),
        "subject_change": round(result.subject_change, 6),
        "group_changes": {k: round(v, 6) for k, v in result.group_changes.items()},
        "peer_change": round(result.peer_change, 6),
        "relative_change": round(result.relative_change, 6),
        "multiplier": round(1 / (1 - result.relative_change), 6),
        "eval_price": round(result.eval_price, 2),
        "scores": {
            k: {"anchor": round(s.anchor, 2), "raw": round(s.raw, 4),
                "value": round(s.value, 2), "clipped": s.clipped}
            for k, s in result.scores.items()
        },
    }


def _coverage(prices: dict[str, list[Bar]]) -> dict:
    gaps = [f.message for f in check_calendar_gaps(prices) if f.level == "error"]
    checks = cross_check_monthly(prices)
    verified = sorted({c.month for c in checks if c.covered and c.exact})
    unverified = sorted({c.month for c in checks if not c.covered})
    mismatched = sorted({c.month for c in checks if c.covered and not c.exact})
    return {"gaps": gaps, "verified_months": verified,
            "unverified_months": unverified, "mismatched_months": mismatched}


def build_latest(
    prices: dict[str, list[Bar]],
    universe: Universe,
    rules: dict,
    calibration: dict,
) -> dict:
    days = trading_days(prices)
    as_of = days[-1]
    prev = days[-2] if len(days) > 1 else None
    specs_prov = rules["windows"]["잠정"]
    method = rules["vwap_primary"]

    # 종목 현황
    vwaps = adjusted_prices(prices, universe, as_of, specs_prov, method,
                            calibration.get("corporate_actions") or [])
    base_vwaps = adjusted_prices(prices, universe, rules["base_date"], specs_prov, method,
                                 calibration.get("corporate_actions") or [])
    tickers = []
    for meta in _ticker_meta(universe):
        by_day = {b.day: b for b in prices[meta["code"]]}
        cur, before = by_day.get(as_of), by_day.get(prev) if prev else None
        tickers.append({
            **meta,
            "close": cur.close if cur else None,
            "volume": cur.volume if cur else None,
            "change_pct": round(cur.close / before.close - 1, 6) if cur and before else None,
            "vwap_2m": round(vwaps[meta["code"]], 2),
            "change_from_base": round(vwaps[meta["code"]] / base_vwaps[meta["code"]] - 1, 6),
            # 표 안 스파크라인용. 최근 40거래일 종가 — 추세만 보이면 되므로 원값 그대로.
            "spark": [b.close for b in prices[meta["code"]][-SPARK_POINTS:]],
        })

    # 평가 시점별 화면. 각 시점마다 잠정·최종을 모두 계산해 나란히 보여준다 —
    # 두 방식의 점수 차이가 어디서 벌어지는지가 이 KPI 의 핵심 논점이다.
    views = [{
        "key": "today", "label": "오늘의 점수", "date": as_of.isoformat(),
        "official_mode": "최종", "confirmed": False,
        "modes": {m: _mode_detail(prices, universe, rules, calibration, as_of, m, method)
                  for m in ("잠정", "최종")},
    }]
    for entry in reversed([e for e in rules["eval_dates"] if e["date"]]):
        views.append({
            "key": entry["label"].replace(" ", "-"), "label": entry["label"],
            "date": entry["date"].isoformat(), "official_mode": entry["mode"], "confirmed": True,
            "modes": {m: _mode_detail(prices, universe, rules, calibration,
                                      entry["date"], m, method)
                      for m in ("잠정", "최종")},
        })

    # 산식 A/B 대조는 공식 방식에서만 필요하다
    method_compare = {m: _result_json(evaluate(prices, universe, rules, calibration,
                                               as_of, "잠정", m))
                      for m in rules["vwap_methods"]}

    upcoming = [e for e in rules["eval_dates"] if e["date"] and e["date"] > as_of]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "base_date": rules["base_date"].isoformat(),
        "method_primary": method,
        "methods": rules["vwap_methods"],
        "score_scale": rules["score_scale"],
        "baselines": {k: {"label": v["label"], "official": bool(v.get("official"))}
                      for k, v in calibration["baselines"].items()},
        "tickers": tickers,
        "views": views,
        "method_compare": method_compare,
        "next_eval": ({"label": upcoming[0]["label"], "date": upcoming[0]["date"].isoformat(),
                       "days": (upcoming[0]["date"] - as_of).days} if upcoming else None),
        "coverage": _coverage(prices),
        "watchlist": calibration.get("watchlist") or [],
    }


def build_scenarios(prices: dict[str, list[Bar]], universe: Universe, rules: dict, calibration: dict) -> dict:
    """탭3(Case 시뮬레이션) 전용 — 12칸 매트릭스 · 잔여기간 경로 · 점수 시계열.

    목표 역산·Peer 기여도·민감도는 탭2 소속이라 `build_latest()` 의 `_mode_detail`
    쪽에 이미 실려 있다(PLAN.md §6 "1·2·3번은 탭2, 4·5번은 탭3").
    """
    days = trading_days(prices)
    as_of = days[-1]
    method = rules["vwap_primary"]

    matrix = score_matrix(prices, universe, rules, calibration, as_of)
    paths = {m: remaining_path_scenarios(prices, universe, rules, calibration, as_of, m, method)
             for m in (1, 2, 3)}
    timeseries = score_timeseries(prices, universe, rules, calibration, days, method)
    events = [{"label": e["label"], "date": e["date"].isoformat()}
              for e in rules["eval_dates"] if e["date"]]
    return {"as_of": as_of.isoformat(), "matrix": matrix, "remaining_paths": paths,
            "timeseries": timeseries, "events": events}


def build_bars(prices: dict[str, list[Bar]]) -> dict:
    """탭4(27년 과제 설계) 전용 원자료 — 클라이언트에서 자유 파라미터로 재계산할 때 쓴다.

    사이트는 계산하지 않는다는 원칙(파일 맨 위 docstring)의 유일한 예외다.
    탭4는 슬라이더 값이 무한하므로 서버에서 미리 계산해 둘 수 없다 — 원자료를
    그대로 내보내고, `docs/assets/sim.js` 가 core/ 의 공식을 그대로 옮겨 재계산한다.
    """
    return {
        code: {
            "dates": [b.day.isoformat() for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
            "trading_value": [b.trading_value for b in bars],
        }
        for code, bars in prices.items()
    }


def build_changelog(repo_root: Path | None = None) -> list[dict]:
    """`config/*.yaml` 변경 이력 — 누가·언제·무엇을 바꿨는지 git 기반으로 뽑는다."""
    root = repo_root or REPO_ROOT
    try:
        out = subprocess.run(
            ["git", "log", "--date=iso-strict", "--pretty=format:%H\x1f%ad\x1f%an\x1f%s", "--", "config"],
            cwd=root, capture_output=True, text=True, check=True, timeout=10,
        ).stdout
    except Exception:
        return []
    entries = []
    for line in out.splitlines():
        if not line:
            continue
        commit_hash, when, author, subject = line.split("\x1f", 3)
        entries.append({"hash": commit_hash[:8], "date": when, "author": author, "subject": subject})
    return entries


def write_site_data(
    prices: dict[str, list[Bar]],
    universe: Universe,
    rules: dict,
    calibration: dict,
    out_dir: Path | None = None,
) -> list[Path]:
    root = out_dir or DOCS_DATA
    root.mkdir(parents=True, exist_ok=True)
    payloads = {
        "latest.json": build_latest(prices, universe, rules, calibration),
        "history.json": build_history(prices, rules["base_date"], universe),
        "scenarios.json": build_scenarios(prices, universe, rules, calibration),
        "bars.json": build_bars(prices),
        "changelog.json": build_changelog(),
    }
    written = []
    for name, payload in payloads.items():
        path = root / name
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
        written.append(path)
    return written
