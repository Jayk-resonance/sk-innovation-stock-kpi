# Daily dashboard update

The recurring Codex task uses PlayMCP for market data and updates `main`
directly only after every check passes.

1. Fast-forward the local `main` branch from `origin/main` and require a clean
   working tree.
2. Read `docs/data/latest.json`, query recent KOSPI index history to determine
   the latest market trading date, and confirm it with SK Innovation (`096770`)
   daily history for the most recent seven calendar days.
3. If the market's latest trading date is not newer than `latest.json`'s
   `as_of`, treat it as a holiday/weekend or an already completed run and exit
   successfully without changing files.
4. Query daily history for all nine tickers from the day after `as_of` through
   the latest trading date. Require the same trading dates for every ticker and
   positive close, volume, and trading value.
5. Save the response as a new immutable `data/raw/*.json` file using the schema
   in `pipeline/COLLECT.md`.
6. Query monthly history for all nine tickers from January 1 through the latest
   trading date. Replace only the latest month in
   `data/reference/monthly.csv`; require its `last_trading_day` to match.
7. Run:

   ```powershell
   .\.venv\Scripts\python.exe -m pipeline.update_daily --expected-date YYYY-MM-DD
   .\.venv\Scripts\python.exe -m pytest -q
   ```

   If `.venv` does not exist, create it and install `requirements.txt` first.
8. Require all 78+ tests to pass, `latest.json.as_of` to equal the new trading
   date, and `coverage.gaps`, `coverage.unverified_months`, and
   `coverage.mismatched_months` to be empty.
9. Review the diff, commit only the collected data, generated dashboard data,
   and directly related pipeline changes, then push `main`.
10. Verify the public GitHub Pages site shows the new date and has no console
    errors. On failure, do not push and send the failure details to
    `kjwgv1442@gmail.com`. Do not send a success email.
