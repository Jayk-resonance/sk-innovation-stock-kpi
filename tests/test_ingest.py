import csv
import json

from pipeline import ingest


FIELDS = ("code", "date", "close", "volume", "trading_value")
OLD = {
    "code": "006400",
    "date": "2026-08-07",
    "close": 459000,
    "volume": 689025,
    "trading_value": 312618245250,
}
CORRECTED = {
    **OLD,
    "volume": 689155,
    "trading_value": 312677779530,
}


def _write_prices(path, row):
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(row)


def _write_raw(path, row):
    path.write_text(
        json.dumps({"prices": [row]}, ensure_ascii=False),
        encoding="utf-8",
    )


def _read_price(path):
    with path.open(encoding="utf-8") as fh:
        return next(csv.DictReader(fh))


def test_merge_raw_ignores_intermediate_value_when_final_value_is_unchanged(
    tmp_path, monkeypatch
):
    prices = tmp_path / "prices.csv"
    shares = tmp_path / "shares.csv"
    original = tmp_path / "2026-08-07.json"
    correction = tmp_path / "2026-08-13-correction.json"
    _write_prices(prices, CORRECTED)
    _write_raw(original, OLD)
    _write_raw(correction, CORRECTED)
    monkeypatch.setattr(ingest, "PRICES_CSV", prices)
    monkeypatch.setattr(ingest, "SHARES_CSV", shares)

    changed, warnings = ingest.merge_raw([correction, original])

    assert changed == 0
    assert warnings == []
    assert _read_price(prices)["volume"] == "689155"


def test_merge_raw_warns_once_when_resolved_value_changes_normalized_data(
    tmp_path, monkeypatch
):
    prices = tmp_path / "prices.csv"
    shares = tmp_path / "shares.csv"
    original = tmp_path / "2026-08-07.json"
    correction = tmp_path / "2026-08-13-correction.json"
    _write_prices(prices, OLD)
    _write_raw(original, OLD)
    _write_raw(correction, CORRECTED)
    monkeypatch.setattr(ingest, "PRICES_CSV", prices)
    monkeypatch.setattr(ingest, "SHARES_CSV", shares)

    changed, warnings = ingest.merge_raw([original, correction])

    assert changed == 1
    assert len(warnings) == 1
    assert "거래량 689025→689155" in warnings[0]
    assert _read_price(prices)["volume"] == "689155"
