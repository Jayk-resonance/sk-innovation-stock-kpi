# Daily dashboard update

The recurring Codex task uses PlayMCP for market data and updates `main`
directly only after every check passes.

1. Fast-forward the local `main` branch from `origin/main` and require a clean
   working tree.
2. Read `docs/data/latest.json` and determine the latest fully completed Korean
   trading date. The dashboard basis is the previous trading day's **unadjusted
   finalized KIS daily bar** from PlayMCP `stock_get_price_history`: close,
   volume, and trading value must come from the same dated response. KIS daily
   volume and trading value may include after-hours/NXT-integrated trades.
   Never substitute a current quote for a dated daily bar.
3. Before deciding that no update is needed, query and compare at least the
   latest 20 stored trading dates for every configured ticker. This comparison
   also runs on weekends, holidays, and already-completed dates. If the market's
   latest date is not newer and all recent values match, exit successfully.
4. Derive the universe from `config/universe.yaml`. Query daily history for all
   nine KPI tickers plus all configured candidates (currently two) from the day
   after `as_of` through the latest trading date. Require the same trading dates
   for every ticker and positive close, volume, and trading value. Reconcile
   month-to-date totals for the nine KPI tickers only.
   Publish only on the next calendar morning; a same-day candle is never eligible.
5. Save the response as a new immutable `data/raw/*.json` file using the schema
   in `pipeline/COLLECT.md`.
6. Replace only the latest month in `data/reference/monthly.csv` with the KIS
   finalized month-to-date totals for the nine KPI tickers and require its
   `last_trading_day` to match. Query the KIS monthly history for the same cutoff
   and require exact equality with the summed daily volume and trading value.
7. Run the update once without correction overrides:

   ```powershell
   .\.venv\Scripts\python.exe -m pipeline.update_daily --expected-date YYYY-MM-DD
   ```

   If the command reports an existing-data correction, do not approve it
   automatically. Query the KIS daily-history source twice for every reported
   ticker/date and require both responses to match the proposed corrected close,
   volume, and trading value. Require the KIS monthly bar to reconcile exactly.
   Only after all checks pass, rerun:

   ```powershell
   .\.venv\Scripts\python.exe -m pipeline.update_daily --expected-date YYYY-MM-DD --allow-corrections
   ```

   Never use `--allow-corrections` when either daily confirmation differs or the
   monthly total does not reconcile. After a successful update, run:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q
   ```

   If `.venv` does not exist, create it and install `requirements.txt` first.
8. Require all 78+ tests to pass, `latest.json.as_of` to equal the new trading
   date, and `coverage.gaps`, `coverage.unverified_months`, and
   `coverage.mismatched_months` to be empty.
9. Review the diff, commit only the collected data, generated dashboard data,
   and directly related pipeline changes, then push `main`.
10. Verify the public GitHub Pages site shows the new date and has no console
    errors. Report deployment problems to the requester.
