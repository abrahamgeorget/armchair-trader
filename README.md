# questrade-sheets

Pulls daily OHLCV data from the Questrade API for an index proxy and a
watchlist of tickers, and appends it to tabs in a Google Sheet. Meant to
be run manually each day for now (`python run_daily.py`); can be put on
a schedule (cron / Task Scheduler / GitHub Actions) later without code
changes.

## One-time setup

### 1. Google service account (so a script can write to Sheets without your login)

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project (or use an existing one).
2. Enable the **Google Sheets API** for that project.
3. Create a **Service Account** (IAM & Admin -> Service Accounts), then
   create a JSON key for it and download it.
4. Save that JSON file as `service_account.json` in this folder (it's
   gitignored, won't be committed).
5. Open your target Google Sheet, click **Share**, and share it with the
   service account's email address (looks like
   `something@your-project.iam.gserviceaccount.com`) as an **Editor**.
6. Copy the Sheet ID out of its URL:
   `https://docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`

### 2. Questrade token

You already activated API access and have a token. Seed the local token
store with it (this file is gitignored):

```bash
echo '{"refresh_token": "PASTE_YOUR_CURRENT_REFRESH_TOKEN"}' > token_store.json
```

Note: the first time `run_daily.py` runs, it will immediately redeem this
token and overwrite `token_store.json` with a new one. That's expected --
Questrade refresh tokens are single-use. Don't hand-edit this file after
that; let the script manage it.

If your token was issued for a **practice/demo** account, set:
```bash
export QT_PRACTICE=1
```

### 3. Environment variables

```bash
export GOOGLE_SHEET_ID="your-sheet-id-from-above"
export GOOGLE_SERVICE_ACCOUNT_PATH="service_account.json"   # default, can omit
```

### 4. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 5. Edit your watchlist

Edit `universe.csv` -- one ticker per line, no `.TO` suffix needed
(the script strips it when matching). Replace the sample tickers with
your actual screening universe.

## Running it

```bash
python run_daily.py
```

Expected output:
```
Wrote 10 rows to 'Index_Daily'.
Wrote 100 rows to 'Universe_OHLCV'.
Done.
```

Check your Sheet -- you should see two tabs populated with a row per
symbol per trading day in the lookback window.

## Known simplifications (v1)

- **No dedup.** Rerunning the same day appends duplicate rows for that
  date. Fine for a manual daily run where you run it once; if you
  automate this on a schedule, add a "delete existing rows for today's
  date before appending" step in `sheets_writer.py`.
- **Index proxy, not the raw index.** Questrade's API is account/security
  oriented, so `INDEX_PROXY_TICKER` (default `XIC`, the iShares S&P/TSX
  Capped Composite ETF) stands in for the Composite. Swap it in
  `config.py` if you'd rather track a different proxy.
- **Fixed 10-day lookback.** `get_daily_candles(..., lookback_days=10)`
  in `run_daily.py` -- bump this if you want a longer history per run.

## Troubleshooting

**`AUTH FAILED: Token refresh failed (400): ...`**
Your stored refresh token is stale, expired (7 days unused), or was
already consumed by another run. Generate a new manual authorization
token in the Questrade API Centre and reseed `token_store.json` as in
step 2 above.

**`WARN: no symbolId found for X`**
The ticker in `universe.csv` doesn't match what `symbols/search` returns.
Try the ticker without a suffix, or check the exact symbol string on
Questrade's site.
