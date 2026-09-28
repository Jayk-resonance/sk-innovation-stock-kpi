# Daily dashboard update

The recurring Codex task uses PlayMCP for market data and updates `main`
directly only after every check passes.

1. Fast-forward the local `main` branch from `origin/main` and require a clean
   working tree.
2. Read `docs/data/latest.json` and determine the latest fully completed Korean
   trading date. The dashboard basis is the previous trading day's **unadjusted
   KRX regular-session daily candle**: 15:30 close, regular-session volume, and
   regular-session trading value from one dated response. Exclude NXT,
   unified-market, and after-hours trades. Never substitute a current quote for
   a dated daily candle.
   Use a source that explicitly identifies the dated candle as KRX regular
   session. The current PlayMCP history tool has no market-division argument, so
   its generic KIS history is not eligible. Until a dated KIS history endpoint
   with `market_div_code="J"` is exposed, use Daum Finance's unadjusted KRX
   daily candle and cross-check every changed/new close with Naver Finance.
3. If the market's latest trading date is not newer than `latest.json`'s
   `as_of`, treat it as a holiday/weekend or an already completed run and exit
   successfully without changing files.
4. Derive the universe from `config/universe.yaml`. Query daily history for all
   nine KPI tickers plus all configured candidates (currently two) from the day
   after `as_of` through the latest trading date. Require the same trading dates
   for every ticker and positive close, volume, and trading value. Reconcile
   month-to-date totals for the nine KPI tickers only.
   Publish only on the next calendar morning. Compare recent stored days to the
   KRX source before appending anything; a same-day candle is never eligible.
5. Save the response as a new immutable `data/raw/*.json` file using the schema
   in `pipeline/COLLECT.md`.
6. Replace only the latest month in `data/reference/monthly.csv` with the KRX
   regular-session month-to-date totals for the nine KPI tickers and require its
   `last_trading_day` to match. If an independently aggregated regular-session
   monthly endpoint is available for the same cutoff, require exact equality;
   otherwise record the daily sums and rely on close cross-check plus coverage
   and positivity checks. Never compare KRX-only daily totals to a KIS generic
   monthly bar that can include after-hours trading.
7. Run the update once without correction overrides:

   ```powershell
   .\.venv\Scripts\python.exe -m pipeline.update_daily --expected-date YYYY-MM-DD
   ```

   If the command reports an existing-data correction, do not approve it
   automatically. Query the KRX regular-session source twice for every reported
   ticker/date and require both daily responses to match the proposed corrected
   close, volume, and trading value. Require a second source to match each
   corrected close. Only after all checks pass, rerun:

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
