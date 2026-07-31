"""Merge collected raw prices, validate them, and rebuild the dashboard data."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from core.schema import load_calibration, load_rules, load_universe
from pipeline.build_site import write_site_data
from pipeline.ingest import PRICES_CSV, load_prices, merge_raw
from pipeline.qc import run_all


def _universe_codes(universe) -> set[str]:
    codes = {universe.subject.code}
    for _, tickers in universe.groups.values():
        codes.update(ticker.code for ticker in tickers)
    return codes


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--expected-date",
        type=date.fromisoformat,
        help="Require every KPI ticker to contain this trading date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--allow-corrections",
        action="store_true",
        help="Accept raw data that changes an existing normalized row.",
    )
    args = parser.parse_args()

    previous_prices = PRICES_CSV.read_bytes()
    changed, correction_warnings = merge_raw()
    if correction_warnings and not args.allow_corrections:
        PRICES_CSV.write_bytes(previous_prices)
        print("Existing data would be corrected; normalized prices were restored.")
        for warning in correction_warnings:
            print(f"- {warning}")
        return 1

    universe = load_universe()
    rules = load_rules()
    calibration = load_calibration()
    prices = load_prices()

    if args.expected_date:
        missing = sorted(
            code
            for code in _universe_codes(universe)
            if not prices.get(code) or prices[code][-1].day != args.expected_date
        )
        if missing:
            print(
                f"{args.expected_date.isoformat()} data is incomplete: "
                + ", ".join(missing)
            )
            return 1

    findings = run_all(prices, universe, start=rules["base_date"])
    for finding in findings:
        print(f"[{finding.level.upper()}] {finding.code}: {finding.message}")
    if any(finding.level == "error" for finding in findings):
        return 1

    written = write_site_data(
        prices, universe, rules, calibration, include_changelog=False
    )
    latest = json.loads(Path("docs/data/latest.json").read_text(encoding="utf-8"))
    if args.expected_date and latest["as_of"] != args.expected_date.isoformat():
        print(f"Unexpected dashboard date: {latest['as_of']}")
        return 1

    print(
        f"Daily update complete: {latest['as_of']}, "
        f"{changed} normalized rows changed, {len(written)} site files written."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
