"""교차검증 및 산출근거 패키지.

**2차 소스 문제.** `pykrx` 는 KRX 계정을 요구하고, 네이버 금융은 프록시가 차단한다.
완전히 독립된 제3의 소스는 현재 환경에서 확보할 수 없다.

대신 **같은 제공자의 다른 집계 경로**를 쓴다. KIS 월봉(`period="M"`)의
거래량·거래대금은 서버측에서 집계된 값이라, 우리가 일봉을 모아 만든 합계와
대조하면 수집 누락·중복·전사 오류가 원 단위로 드러난다.
실제로 이 방식이 2026-05-26/27 결측을 잡아낸 것과 동일한 종류의 오류를 잡는다.

한계는 분명하다 — KIS 자체가 틀린 경우는 잡지 못한다.
이 검사가 보증하는 것은 **"우리가 KIS 데이터를 온전히 옮겼다"** 까지다.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from core.calendar import window_bounds
from core.evaluate import Result, adjusted_prices, evaluate
from core.schema import Bar, Universe
from core.vwap import slice_spec_window, vwap
from pipeline.qc import GAP_ERROR_DAYS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
MONTHLY_REF = DATA_DIR / "reference" / "monthly.csv"

VWAP_TOLERANCE = 0.001  # ±0.1%


@dataclass
class MonthCheck:
    code: str
    month: str
    daily_volume: int
    ref_volume: int
    daily_value: int
    ref_value: int
    covered: bool  # 그 달을 통째로 수집했는가

    @property
    def exact(self) -> bool:
        return self.daily_volume == self.ref_volume and self.daily_value == self.ref_value

    @property
    def vwap_error(self) -> float | None:
        if not self.daily_volume or not self.ref_volume:
            return None
        return abs((self.daily_value / self.daily_volume) / (self.ref_value / self.ref_volume) - 1)

    @property
    def verdict(self) -> str:
        """부분 수집한 달은 판정하지 않는다.

        월봉은 그 달 전체의 집계다. 달의 일부만 수집한 상태에서 대조하면
        정상적인 부분 수집이 '결측'으로 오인된다. 검증할 수 없는 것을
        검증했다고 하지 않는 편이 낫다.
        """
        if not self.covered:
            return "검증불가(부분수집)"
        if self.exact:
            return "일치"
        return "결측" if self.daily_volume < self.ref_volume else "중복"


def _contiguous_runs(days: list[date], max_gap: int = GAP_ERROR_DAYS) -> list[tuple[date, date]]:
    """수집 구간을 공백 기준으로 쪼갠다.

    임계값은 `qc.GAP_ERROR_DAYS` 와 같아야 한다. 더 짧게 잡으면 설·추석 연휴가
    수집 공백으로 오인되어, 완전히 수집한 달이 '검증불가'로 잘못 분류된다.
    (2026년 설 연휴 2/14~2/18 이 실제로 그렇게 걸렸다.)
    """
    if not days:
        return []
    runs, start = [], days[0]
    for prev, cur in zip(days, days[1:]):
        if (cur - prev).days > max_gap:
            runs.append((start, prev))
            start = cur
    runs.append((start, days[-1]))
    return runs


def _month_bounds(month: str) -> tuple[date, date]:
    year, mon = int(month[:4]), int(month[5:])
    first = date(year, mon, 1)
    last = date(year + (mon == 12), mon % 12 + 1, 1) - __import__("datetime").timedelta(days=1)
    return first, last


def _is_covered(month: str, runs: list[tuple[date, date]], data_max: date,
                last_trading_day: date) -> bool:
    """그 달을 통째로 수집했는가.

    달력 말일이 아니라 **그 달 마지막 거래일**을 기준으로 본다.
    2025-12-31 은 휴장이라 12-30 이 마지막 거래일인데, 달력 말일로 판정하면
    완전히 수집한 12월이 '검증불가'로 잘못 분류된다.
    """
    first, _ = _month_bounds(month)
    for start, end in runs:
        if start <= first and end >= min(last_trading_day, data_max):
            return True
    return False


def load_monthly_reference(path: Path | None = None) -> dict[tuple[str, str], tuple[int, int, date]]:
    """(거래량, 거래대금, 그 달 마지막 거래일)."""
    with (path or MONTHLY_REF).open(encoding="utf-8") as fh:
        return {
            (r["code"], r["month"]): (int(r["volume"]), int(r["trading_value"]),
                                      date.fromisoformat(r["last_trading_day"]))
            for r in csv.DictReader(fh)
        }


def cross_check_monthly(
    prices: dict[str, list[Bar]], reference: dict[tuple[str, str], tuple[int, int]] | None = None
) -> list[MonthCheck]:
    """일봉 합계를 KIS 월봉 집계와 대조한다. 우리가 가진 월만 검사한다."""
    ref = reference if reference is not None else load_monthly_reference()
    checks = []
    for code, bars in sorted(prices.items()):
        days = [b.day for b in bars]
        runs, data_max = _contiguous_runs(days), days[-1]
        months: dict[str, list[Bar]] = {}
        for bar in bars:
            months.setdefault(bar.day.strftime("%Y-%m"), []).append(bar)
        for month, rows in sorted(months.items()):
            if (code, month) not in ref:
                continue
            ref_vol, ref_val, last_td = ref[(code, month)]
            checks.append(
                MonthCheck(
                    code=code,
                    month=month,
                    daily_volume=sum(b.volume for b in rows),
                    ref_volume=ref_vol,
                    daily_value=sum(b.trading_value for b in rows),
                    ref_value=ref_val,
                    covered=_is_covered(month, runs, data_max, last_td),
                )
            )
    return checks


def verify_windows(
    prices: dict[str, list[Bar]],
    universe: Universe,
    eval_date: date,
    specs: list[str],
    reference: dict[tuple[str, str], tuple[int, int]] | None = None,
) -> tuple[bool, list[MonthCheck]]:
    """평가 윈도우가 걸치는 달만 골라 검증한다.

    평가에 실제로 쓰이는 구간만 보므로, 윈도우 밖 미수집 구간이
    분기 평가 판정을 오염시키지 않는다.
    """
    touched = set()
    for spec in specs:
        if spec.upper().endswith("W"):
            subject_bars = slice_spec_window(prices[universe.subject.code], eval_date, spec)
            start, end = subject_bars[0].day, subject_bars[-1].day
        else:
            start, end = window_bounds(eval_date, spec)
        cur = start
        while cur <= end:
            touched.add(cur.strftime("%Y-%m"))
            cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    relevant = [c for c in cross_check_monthly(prices, reference) if c.month in touched]
    verified = [c for c in relevant if c.covered]
    return bool(verified) and all(c.exact for c in verified), relevant


def _fmt(value: float) -> str:
    return f"{value:.6f}"


def build_evidence_package(
    prices: dict[str, list[Bar]],
    universe: Universe,
    rules: dict,
    calibration: dict,
    eval_date: date,
    mode: str,
    method: str,
    label: str,
    out_dir: Path | None = None,
) -> Path:
    """분기 평가 산출근거 패키지.

    제3자가 원자료부터 점수까지 손으로 따라올 수 있어야 한다.
    """
    root = (out_dir or REPORTS_DIR) / label
    root.mkdir(parents=True, exist_ok=True)
    specs = rules["windows"][mode]
    result = evaluate(prices, universe, rules, calibration, eval_date, mode, method)

    # 1. 원자료 — 평가에 쓰인 봉 전부
    with (root / "01_raw_bars.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "name", "window", "date", "close", "volume", "trading_value"])
        for ticker in universe.all_tickers:
            for spec in specs:
                for which, anchor in (("평가일", eval_date), ("기준일", rules["base_date"])):
                    bars = slice_spec_window(prices[ticker.code], anchor, spec)
                    for bar in bars:
                        w.writerow([ticker.code, ticker.name, f"{which}/{spec}",
                                    bar.day, bar.close, bar.volume, bar.trading_value])

    # 2. 윈도우별 VWAP 중간값
    with (root / "02_vwap.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "name", "기준", "window", "start", "end", "days", "vwap"])
        for ticker in universe.all_tickers:
            for which, anchor in (("평가일", eval_date), ("기준일", rules["base_date"])):
                for spec in specs:
                    bars = slice_spec_window(prices[ticker.code], anchor, spec)
                    start, end = bars[0].day, bars[-1].day
                    w.writerow([ticker.code, ticker.name, which, spec, start, end,
                                len(bars), _fmt(vwap(bars, method))])

    # 3. 증감율 → 점수 전 단계 추적
    now = adjusted_prices(prices, universe, eval_date, specs, method,
                          calibration.get("corporate_actions") or [])
    base = adjusted_prices(prices, universe, rules["base_date"], specs, method,
                           calibration.get("corporate_actions") or [])
    with (root / "03_trace.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["항목", "값"])
        for ticker in universe.all_tickers:
            w.writerow([f"{ticker.name} 보정주가(평가일)", _fmt(now[ticker.code])])
            w.writerow([f"{ticker.name} 보정주가(기준일)", _fmt(base[ticker.code])])
            w.writerow([f"{ticker.name} 증감율", _fmt(now[ticker.code] / base[ticker.code] - 1)])
        for name, value in result.group_changes.items():
            weight = universe.groups[name][0]
            w.writerow([f"{name} 그룹 평균 증감율", _fmt(value)])
            w.writerow([f"{name} 가중치", weight])
        w.writerow(["Peer 증감율", _fmt(result.peer_change)])
        w.writerow(["SK 증감율", _fmt(result.subject_change)])
        w.writerow(["상대 증감율 x", _fmt(result.relative_change)])
        w.writerow(["배수 1/(1-x)", _fmt(1 / (1 - result.relative_change))])
        w.writerow(["SK 거래량보정주가(평가일)", _fmt(result.subject_price)])
        w.writerow(["평가주가", _fmt(result.eval_price)])
        for key, score in sorted(result.scores.items()):
            w.writerow([f"{key} 앵커", _fmt(score.anchor)])
            w.writerow([f"{key} 점수(원값)", _fmt(score.raw)])
            w.writerow([f"{key} 점수(확정)", _fmt(score.value)])

    # 4. 교차검증
    ok, checks = verify_windows(prices, universe, eval_date, specs)
    with (root / "04_cross_check.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "month", "일봉합_거래량", "월봉_거래량",
                    "일봉합_거래대금", "월봉_거래대금", "판정"])
        for c in checks:
            w.writerow([c.code, c.month, c.daily_volume, c.ref_volume,
                        c.daily_value, c.ref_value, c.verdict])

    (root / "00_SUMMARY.md").write_text(_summary(result, label, ok, checks), encoding="utf-8")
    return root


def _coverage_line(ok: bool, checks: list[MonthCheck]) -> str:
    """검증된 것과 검증하지 못한 것을 나누어 표기한다."""
    verified = [c for c in checks if c.covered]
    unverified = sorted({c.month for c in checks if not c.covered})
    head = f"{'✅ 검증 구간 원 단위 일치' if ok else '❌ 불일치 있음'} ({len(verified)}건)"
    if unverified:
        head += f" · ⊘ 검증불가 {', '.join(unverified)} (달 일부만 수집)"
    return head


def _summary(result: Result, label: str, ok: bool, checks: list[MonthCheck]) -> str:
    lines = [
        f"# {label} 산출근거",
        "",
        f"- 평가일: {result.eval_date}",
        f"- 평가 방식: {result.mode} / VWAP 산식 {result.method}",
        f"- 교차검증: {_coverage_line(ok, checks)}",
        "",
        "## 산출",
        "",
        "| 항목 | 값 |",
        "|---|---:|",
        f"| SK 증감율 | {result.subject_change * 100:+.2f}% |",
    ]
    for name, value in result.group_changes.items():
        lines.append(f"| {name} 그룹 평균 | {value * 100:+.2f}% |")
    lines += [
        f"| Peer 증감율 | {result.peer_change * 100:+.2f}% |",
        f"| 상대 증감율 x | {result.relative_change * 100:+.2f}% |",
        f"| SK 거래량보정주가 | {result.subject_price:,.0f}원 |",
        f"| 평가주가 | {result.eval_price:,.0f}원 |",
        "",
        "## 기준선별 점수",
        "",
        "| 기준선 | 앵커 | 원값 | 확정 | 클리핑 |",
        "|---|---:|---:|---:|---|",
    ]
    for key, score in sorted(result.scores.items()):
        lines.append(
            f"| {key} | {score.anchor:,.0f}원 | {score.raw:+.2f}점 | "
            f"**{score.value:.2f}점** | {'예' if score.clipped else '아니오'} |"
        )
    lines += ["", "## 첨부", "",
              "- `01_raw_bars.csv` — 평가에 사용된 일별 원자료 전량",
              "- `02_vwap.csv` — 종목·윈도우별 VWAP 중간값",
              "- `03_trace.csv` — 증감율부터 점수까지 전 단계",
              "- `04_cross_check.csv` — KIS 월봉 대조 결과", ""]
    return "\n".join(lines)
