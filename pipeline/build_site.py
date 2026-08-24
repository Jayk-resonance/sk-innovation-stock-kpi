"""계산 결과 → 사이트 데이터(JSON).

사이트는 계산하지 않는다. 여기서 만든 JSON을 읽어 그리기만 한다.
계산은 `core/` 한 곳에만 있어야 검증 결과가 사이트에도 그대로 적용된다.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import subprocess

from core.calendar import minus_months
from core.evaluate import adjusted_prices, base_adjusted_prices, evaluate, price_for_points
from core.scenarios import (
    peer_waterfall,
    remaining_path_scenarios,
    score_matrix,
    score_timeseries,
    sensitivity_table,
    target_price,
)
from core.schema import Bar, Universe, load_candidates, load_peer_criteria
from pipeline.ingest import load_shares
from pipeline.qc import GAP_ERROR_DAYS, check_calendar_gaps, trading_days
from pipeline.verify import cross_check_monthly

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DATA = REPO_ROOT / "docs" / "data"
DOCS_ROOT = REPO_ROOT / "docs"
TARGET_MARKS = (0, 40, 80, 100)
BASE_INDEX = 100.0
SPARK_POINTS = 40   # 표 스파크라인이 쓰는 최근 거래일 수
LIQUIDITY_WINDOW = 20  # Peer 유동성 평가에 쓰는 최근 거래일 수
VERSIONED_ASSETS = ("style.css", "sim.js", "app.js")  # index.html 이 ?v=해시로 참조하는 파일들


def _ticker_meta(universe: Universe) -> list[dict]:
    out = [{"code": universe.subject.code, "name": universe.subject.name,
            "group": "본사", "weight": None}]
    for group, (weight, members) in universe.groups.items():
        out += [{"code": t.code, "name": t.name, "group": group, "weight": weight}
                for t in members]
    return out


def _market_cap_rating(ratio: float | None) -> str:
    """0.5~2배는 규모가 비슷해 그룹 평균에서 한 종목이 과대표되지 않는다는
    경험칙. 임계값은 판단이지 물리법칙이 아니므로 화면에도 이 기준을 그대로
    표기해 근거를 숨기지 않는다."""
    if ratio is None:
        return "확인 불가"
    if 0.5 <= ratio <= 2.0:
        return "적정"
    if 0.2 <= ratio < 0.5 or 2.0 < ratio <= 4.0:
        return "격차 있음"
    return "격차 큼"


def _latest_cap(shares: dict[str, list[tuple[date, int]]], code: str) -> int | None:
    rows = shares.get(code)
    return rows[-1][1] if rows else None


def _avg_trading_value(prices: dict[str, list[Bar]], code: str) -> float | None:
    bars = prices.get(code)
    if not bars:
        return None
    recent = bars[-LIQUIDITY_WINDOW:]
    return sum(b.trading_value for b in recent) / len(recent)


def _evaluate_tickers(
    tickers, rank_pool, prices: dict[str, list[Bar]],
    shares: dict[str, list[tuple[date, int]]], curated: dict[str, dict],
    subject_cap: int | None,
) -> dict[str, dict]:
    """Peer 선정 적정성 4개 기준을 종목 목록에 대해 계산한다.

    ①사업 유사도 ④독립성(이해상충)은 판단이 들어가므로 config/peer_criteria.yaml
    에 사람이 등록한 값을 그대로 쓴다. ②시가총액 ③거래 유동성은 최신 시세로
    매번 다시 계산해, 데이터가 갱신되면 화면도 그대로 따라온다. 유동성 순위는
    출력 대상(tickers)이 아니라 rank_pool 전체 안에서 매긴다 — 공식 Peer와
    실험용 후보를 같은 "n개사 중 m위" 기준으로 비교할 수 있어야 하므로, 그룹이
    다르거나 후보/공식 여부가 달라도 항상 같은 모집단(공식 Peer 전체 + 후보
    전체)으로 순위를 매긴다.
    """
    liquidity = {t.code: _avg_trading_value(prices, t.code) for t in rank_pool}
    ranked = sorted((c for c in liquidity if liquidity[c] is not None),
                     key=lambda c: liquidity[c], reverse=True)

    out = {}
    for t in tickers:
        cap = _latest_cap(shares, t.code)
        ratio = cap / subject_cap if cap and subject_cap else None
        entry = curated.get(t.code, {})
        out[t.code] = {
            "business_match": entry.get("business_match"),
            "independence": entry.get("independence"),
            "market_cap": {
                "value_100m": cap,
                "ratio_to_subject": round(ratio, 3) if ratio is not None else None,
                "rating": _market_cap_rating(ratio),
            },
            "liquidity": {
                "avg_daily_trading_value": (
                    round(liquidity[t.code]) if liquidity.get(t.code) is not None else None
                ),
                "window_days": LIQUIDITY_WINDOW,
                "rank": ranked.index(t.code) + 1 if t.code in ranked else None,
                "of": len(ranked),
            },
        }
    return out


def _peer_evaluation(prices: dict[str, list[Bar]], universe: Universe) -> dict[str, dict]:
    curated = load_peer_criteria()
    shares = load_shares()
    subject_cap = _latest_cap(shares, universe.subject.code)
    pool = universe.peers + tuple(c.ticker for c in load_candidates())
    return _evaluate_tickers(universe.peers, pool, prices, shares, curated, subject_cap)


def _candidate_evaluation(
    prices: dict[str, list[Bar]], universe: Universe, candidates,
) -> list[dict]:
    """실험용 후보를 공식 Peer 8개 + 후보 전체와 함께 평가한다(유동성 순위 기준).

    candidates 는 core.schema.Candidate 목록이다(config/universe.yaml 의
    candidates 섹션). 이 결과는 오늘의 점수(build_latest 의 tickers/views)에는
    전혀 쓰이지 않고, 탭4 시뮬레이터의 후보 hover 설명에만 쓰인다. 유동성 순위는
    _peer_evaluation 과 같은 모집단(공식 Peer + 후보 전체)을 써서, 공식 Peer
    hover 와 후보 hover 의 "n개사 중" 이 항상 같은 n 을 가리키게 한다.
    """
    curated = load_peer_criteria()
    shares = load_shares()
    subject_cap = _latest_cap(shares, universe.subject.code)
    pool = universe.peers + tuple(c.ticker for c in candidates)
    evaluated = _evaluate_tickers(
        tuple(c.ticker for c in candidates), pool, prices, shares, curated, subject_cap
    )
    return [{
        "code": cand.ticker.code, "name": cand.ticker.name,
        "market": cand.ticker.market, "group": cand.group,
        "peer_eval": evaluated[cand.ticker.code],
    } for cand in candidates]


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
    from core.vwap import adjusted_price, apply_corporate_actions, slice_spec_window, slice_window, vwap

    specs = rules["windows"][mode]
    base_ranges = (rules.get("base_window_ranges") or {}).get(mode)
    actions = calibration.get("corporate_actions") or []
    result = evaluate(prices, universe, rules, calibration, eval_date, mode, method)
    subject = universe.subject.code

    def windows(code, anchor_date, window_ranges=None):
        bars = apply_corporate_actions(prices[code], code, actions)
        rows = []
        for spec in specs:
            window_bars = (
                slice_window(bars, *window_ranges[spec])
                if window_ranges and spec in window_ranges
                else slice_spec_window(bars, anchor_date, spec)
            )
            rows.append({
                "spec": spec,
                "start_date": window_bars[0].day.isoformat(),
                "end_date": window_bars[-1].day.isoformat(),
                "vwap": round(adjusted_price(bars, anchor_date, [spec], method, window_ranges), 2),
            })
        return rows

    subject_bars = apply_corporate_actions(prices[subject], subject, actions)
    subject_by_day = {bar.day: bar for bar in subject_bars}

    def daily_weighted_price(bar):
        """대시보드 기본 산식으로 계산한 1일 거래량가중평균 주가."""
        return round(vwap([bar], method), 2)

    def subject_chart() -> list[dict]:
        """단순 종가와 평가 방식별 거래량가중평균 주가의 일별 추이."""
        start = minus_months(rules["base_date"], 2) + timedelta(days=1)
        rows = []
        for bar in subject_bars:
            if not start <= bar.day <= eval_date:
                continue
            chart_ranges = base_ranges if bar.day == rules["base_date"] else None
            rows.append({
                "date": bar.day.isoformat(),
                "close": bar.close,
                "daily_weighted_price": daily_weighted_price(bar),
                "vwap_2m": round(
                    adjusted_price(subject_bars, bar.day, ["2M"], method, chart_ranges), 2
                ),
                "vwap_final": round(
                    adjusted_price(
                        subject_bars, bar.day, ["2M", "1M", "1W"], method, chart_ranges
                    ), 2
                ),
            })
        return rows

    now = adjusted_prices(prices, universe, eval_date, specs, method, actions)
    base = base_adjusted_prices(prices, universe, rules, mode, method, actions)

    groups = {}
    for name, (weight, members) in universe.groups.items():
        groups[name] = {
            "weight": weight,
            "average": round(result.group_changes[name], 6),
            "members": [{
                "name": t.name,
                "code": t.code,
                "change": round(now[t.code] / base[t.code] - 1, 6),
                "price": round(now[t.code], 2),
                "base_price": round(base[t.code], 2),
                "windows_now": windows(t.code, eval_date),
                "windows_base": windows(t.code, rules["base_date"], base_ranges),
            } for t in members],
        }

    return {
        **_result_json(result),
        "specs": specs,
        "subject_close": subject_by_day[eval_date].close,
        "subject_base_close": subject_by_day[rules["base_date"]].close,
        "subject_daily_weighted_price": daily_weighted_price(subject_by_day[eval_date]),
        "subject_base_daily_weighted_price": daily_weighted_price(
            subject_by_day[rules["base_date"]]
        ),
        "subject_chart": subject_chart(),
        "windows_now": windows(subject, eval_date),
        "windows_base": windows(subject, rules["base_date"], base_ranges),
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
    specs_final = rules["windows"]["최종"]
    method = rules["vwap_primary"]

    # 종목 현황
    evaluation_prices = adjusted_prices(prices, universe, as_of, specs_final, method,
                                        calibration.get("corporate_actions") or [])
    base_evaluation_prices = base_adjusted_prices(
        prices, universe, rules, "최종", method,
        calibration.get("corporate_actions") or [],
    )
    peer_eval = _peer_evaluation(prices, universe)
    tickers = []
    for meta in _ticker_meta(universe):
        by_day = {b.day: b for b in prices[meta["code"]]}
        cur, before = by_day.get(as_of), by_day.get(prev) if prev else None
        tickers.append({
            **meta,
            "close": cur.close if cur else None,
            "previous_close": before.close if before else None,
            "volume": cur.volume if cur else None,
            "change_pct": round(cur.close / before.close - 1, 6) if cur and before else None,
            "evaluation_price": round(evaluation_prices[meta["code"]], 2),
            "change_from_base": round(
                evaluation_prices[meta["code"]] / base_evaluation_prices[meta["code"]] - 1, 6
            ),
            # 표 안 스파크라인용. 최근 40거래일 종가 — 추세만 보이면 되므로 원값 그대로.
            "spark": [b.close for b in prices[meta["code"]][-SPARK_POINTS:]],
            **({"peer_eval": peer_eval[meta["code"]]} if meta["code"] in peer_eval else {}),
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
        "base_window_ranges": {
            mode: {
                spec: {"start": start.isoformat(), "end": end.isoformat()}
                for spec, (start, end) in ranges.items()
            }
            for mode, ranges in rules["base_window_ranges"].items()
        },
        "baselines": {k: {"label": v["label"], "official": bool(v.get("official"))}
                      for k, v in calibration["baselines"].items()},
        "tickers": tickers,
        "views": views,
        "method_compare": method_compare,
        "next_eval": ({"label": upcoming[0]["label"], "date": upcoming[0]["date"].isoformat(),
                       "days": (upcoming[0]["date"] - as_of).days} if upcoming else None),
        "coverage": _coverage(prices),
        "watchlist": calibration.get("watchlist") or [],
        "candidates": _candidate_evaluation(prices, universe, load_candidates()),
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
    timeseries = score_timeseries(
        prices, universe, rules, calibration, days, method, mode="최종", baseline_key="V2"
    )
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
            cwd=root, capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=True, timeout=10,
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


def _blob_hash(path: Path) -> str:
    """git 저장소의 blob SHA-1과 같은 값이 나오는 7자리 해시(`git hash-object` 와 동일)."""
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()[:7]


def sync_asset_versions(docs_root: Path | None = None) -> Path | None:
    """`docs/index.html` 의 asset `?v=` 해시를 실제 파일 내용에 맞춘다.

    브라우저가 `app.js`/`style.css`/`sim.js` 를 오래 캐시하므로, 파일을 고치고
    이 해시를 갱신하는 걸 잊으면 배포 후에도 예전 코드가 계속 실행된다 —
    데이터는 최신인데 화면 로직만 옛날 것으로 돌아가는 버그가 된다
    (2026-08-13 hover 죽은 영역 수정이 실제로 이렇게 묻혔다). 사람이 커밋마다
    수동으로 맞추는 대신, 사이트를 빌드할 때마다 여기서 자동으로 맞춘다.
    """
    root = docs_root or DOCS_ROOT
    index_path = root / "index.html"
    if not index_path.exists():
        return None
    html = index_path.read_text(encoding="utf-8")
    original = html
    for name in VERSIONED_ASSETS:
        asset_path = root / "assets" / name
        if not asset_path.exists():
            continue
        new_hash = _blob_hash(asset_path)
        # 해시값 자체는 임의 문자일 수 있으므로(오타·플레이스홀더 포함) 따옴표
        # 앞까지 통째로 바꾼다 — 형식을 hex 로 가정하면 깨진 값을 못 고친다.
        pattern = re.compile(rf'(assets/{re.escape(name)}\?v=)[^"\']+')
        html = pattern.sub(rf"\g<1>{new_hash}", html)
    if html == original:
        return None
    index_path.write_text(html, encoding="utf-8")
    return index_path


def write_site_data(
    prices: dict[str, list[Bar]],
    universe: Universe,
    rules: dict,
    calibration: dict,
    out_dir: Path | None = None,
    include_changelog: bool = True,
) -> list[Path]:
    root = out_dir or DOCS_DATA
    root.mkdir(parents=True, exist_ok=True)
    payloads = {
        "latest.json": build_latest(prices, universe, rules, calibration),
        "history.json": build_history(prices, rules["base_date"], universe),
        "scenarios.json": build_scenarios(prices, universe, rules, calibration),
        "bars.json": build_bars(prices),
    }
    if include_changelog:
        payloads["changelog.json"] = build_changelog()
    written = []
    for name, payload in payloads.items():
        path = root / name
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
        written.append(path)
    synced_index = sync_asset_versions(root.parent)
    if synced_index:
        written.append(synced_index)
    return written
