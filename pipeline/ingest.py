"""원자료 → 정규화 시계열.

`data/raw/*.json` 을 읽어 `data/normalized/prices.csv` 로 병합한다.
원자료는 절대 수정하지 않는다. 정규화본은 언제든 원자료에서 재생성 가능하다.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
PRICES_CSV = DATA_DIR / "normalized" / "prices.csv"
SHARES_CSV = DATA_DIR / "normalized" / "shares.csv"

PRICE_FIELDS = ("code", "date", "close", "volume", "trading_value")
SHARE_FIELDS = ("code", "date", "market_cap_100m", "price", "shares")


def _read_csv(path: Path) -> dict[tuple[str, str], dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return {(r["code"], r["date"]): r for r in csv.DictReader(fh)}


def _write_csv(path: Path, fields: tuple[str, ...], rows: dict[tuple[str, str], dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for key in sorted(rows):
            writer.writerow({f: rows[key][f] for f in fields})


def merge_raw(raw_files: list[Path] | None = None) -> tuple[int, list[str]]:
    """원자료를 정규화본에 병합한다. (반영 건수, 정정 경고) 를 반환한다.

    같은 (종목, 날짜) 가 다른 값으로 다시 들어오면 **덮어쓰되 경고한다.**
    데이터 정정은 실제로 일어나므로 막지는 않되, 조용히 넘기지도 않는다.
    """
    files = sorted(raw_files if raw_files is not None else RAW_DIR.glob("*.json"))
    prices, shares = _read_csv(PRICES_CSV), _read_csv(SHARES_CSV)
    changed, warnings = 0, []

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("prices", []):
            key = (row["code"], row["date"])
            new = {f: str(row[f]) for f in PRICE_FIELDS}
            old = prices.get(key)
            if old and any(old[f] != new[f] for f in PRICE_FIELDS):
                warnings.append(
                    f"{key[0]} {key[1]} 값 변경: "
                    f"종가 {old['close']}→{new['close']}, 거래량 {old['volume']}→{new['volume']}"
                )
            if old != new:
                prices[key] = new
                changed += 1
        for row in payload.get("shares", []):
            shares[(row["code"], row["date"])] = {f: str(row[f]) for f in SHARE_FIELDS}

    _write_csv(PRICES_CSV, PRICE_FIELDS, prices)
    if shares:
        _write_csv(SHARES_CSV, SHARE_FIELDS, shares)
    return changed, warnings


def load_prices(path: Path | None = None) -> dict[str, list]:
    """정규화본을 core 계층이 쓰는 Bar 목록으로 읽는다."""
    from core.schema import Bar  # 지연 import — pipeline 은 core 에만 의존한다

    out: dict[str, list[Bar]] = {}
    with (path or PRICES_CSV).open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["code"], []).append(
                Bar(
                    day=date.fromisoformat(row["date"]),
                    close=int(row["close"]),
                    volume=int(row["volume"]),
                    trading_value=int(row["trading_value"]),
                )
            )
    for bars in out.values():
        bars.sort(key=lambda b: b.day)
    return out


def load_shares(path: Path | None = None) -> dict[str, list[tuple[date, int]]]:
    """종목별 (날짜, 시가총액 억원) 시계열. 과거 소급이 안 돼 수집 개시일부터 쌓인다."""
    target = path or SHARES_CSV
    out: dict[str, list[tuple[date, int]]] = {}
    if not target.exists():
        return out
    with target.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["code"], []).append(
                (date.fromisoformat(row["date"]), int(row["market_cap_100m"]))
            )
    for rows in out.values():
        rows.sort(key=lambda r: r[0])
    return out
