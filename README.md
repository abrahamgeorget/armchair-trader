# armchair-trader

The goal of this project is to identify stocks with 3-5% gains in a week based on price trends in the last few months and publicly available data. It pulls daily OHLCV data from your brokerage account API for an index proxy and a watchlist of tickers after trading hours, and appends it to tabs in a Google Sheet. Meant to be run manually each day for now (`python run_daily_v2.py`). The buy predictions for stocks are meant to be executed at market open price on the next trading day.

Supports two markets from the same codebase -- TSX (default) and
NASDAQ -- switched with one environment variable, `MARKET`. See
"Switching markets" below.

Note: This is not investment advice , but a prediction project
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

There are **two separate spreadsheets** in this setup, and the service
account needs step 5 (share as Editor) done on **both**:
- `GOOGLE_SHEET_ID` -- the raw daily OHLCV pull (`Index_Daily*` /
  `Universe_OHLCV*` tabs), written by `run_daily_v2.py`.
- `GOOGLE_OUTPUT_SHEET_ID` -- Abe's results-tracking sheet, where the
  aggressive screens' final shortlist gets written (`List_agg` for TSX,
  `List_agg_NASDAQ` for Nasdaq -- same sheet, separate tabs so the two
  markets' results never mix). Defaults to
  `12B85W-6NHXhROMg50tHAG3OVxSz16OssCzM1iDMbSW8` if you don't override it.
  If `write_list_agg.py` fails with a permission error, this sheet not
  being shared with the service account is the first thing to check.

### 2. Brokerage token

You already activated API access and have a token. Seed the local token
store with it (this file is gitignored):

```bash
echo '{"refresh_token": "PASTE_YOUR_CURRENT_REFRESH_TOKEN"}' > token_store.json
```

Note: the first time `run_daily_v2.py` runs, it will immediately redeem this
token and overwrite `token_store.json` with a new one. That's expected --
Questrade refresh tokens are single-use. Don't hand-edit this file after
that; let the script manage it.

If your token was issued for a **practice/demo** account, set:
```bash
export QT_PRACTICE=1
```

### 3. Environment variables

```bash
export GOOGLE_SHEET_ID="your-sheet-id-from-above"           # raw OHLCV
export GOOGLE_OUTPUT_SHEET_ID="your-results-sheet-id"        # screen output (List_agg / List_agg_NASDAQ) -- has a default, see below
export GOOGLE_SERVICE_ACCOUNT_PATH="service_account.json"   # default, can omit
```

### 4. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 5. Edit your watchlist

Edit `universe.csv` (TSX) / `universe_nasdaq.csv` (Nasdaq) -- one ticker
per line, no `.TO` suffix needed for TSX (the script strips it when
matching).

## Switching markets

Everything is driven by one environment variable, `MARKET`, read in
`config.py`. Default is `TSX` -- nothing changes for you if you don't set
it. To run the Nasdaq side instead, set it once per terminal session
before running any script:

```bash
# Windows (cmd.exe)
set MARKET=NASDAQ

# bash
export MARKET=NASDAQ
```

What `MARKET=NASDAQ` changes (all in `config.py`, nothing to edit by hand):

| | TSX (default) | NASDAQ |
|---|---|---|
| Universe file | `universe.csv` (215 tickers) | `universe_nasdaq.csv` (1,006 tickers) |
| Index/universe proxy | XIC (iShares S&P/TSX Capped Composite) | ONEQ (Fidelity Nasdaq Composite Index) |
| Sheet tabs | `Index_Daily`, `Universe_OHLCV`, `List_agg` | `Index_Daily_NASDAQ`, `Universe_OHLCV_NASDAQ`, `List_agg_NASDAQ` |
| Min price | $5.00 CAD | $5.00 USD |
| Min 20-day $ volume | $5,000,000 CAD | $10,000,000 USD |
| Currency | CAD | USD |

Run the daily pull for Nasdaq the same way as TSX, just with the env var
set first:
```bash
set MARKET=NASDAQ
python run_daily_v2.py
```

And the aggressive screen (see the `qsx-nasdaq-aggressive` Claude Code
skill/command for the full chat-driven workflow):
```bash
set MARKET=NASDAQ
python run_qsx_aggresive.py
python write_list_agg.py qsx_candidates_nasdaq.csv
```

**Sector data:** `sector_map_nasdaq.csv` (ticker, GICS sector) sits next to
`universe_nasdaq.csv`, same role as TSX's `sector_map.csv`. Unlike the TSX
version (built straight from XIC's own holdings export), 1,003 of the 1,006
Nasdaq tickers were matched against a third-party GICS-labeled dataset
(JerBouma/FinanceDatabase) rather than an exchange-published file, and 3
(`DSG`, `TRMD.A`, `PSQL`) were filled in individually. Treat it as
good-enough-for-screening, not as authoritative as the TSX one.


## Running it

```bash
python run_daily_v2.py
```

Expected output:
```
Market: TSX  (index proxy XIC, universe universe.csv, tabs 'Index_Daily' / 'Universe_OHLCV')
Wrote 10 rows to 'Index_Daily'.
Wrote 100 rows to 'Universe_OHLCV'.
Done.
```

Check your Sheet -- you should see two tabs populated with a row per
symbol per trading day in the lookback window.

## Running skills

Refer to the skill_trade zip file for the 3 Claude skills that drive the daily screen. 

| `qsx-stock-aggresive` | Scores the TSX universe with screen v2, verifies a fresh company catalyst for each name, and writes the shortlist to the `List_agg` tab. |
| `qsx-nasdaq-aggressive` | Does the same for Nasdaq (USD, ONEQ index proxy) and writes to the `List_agg_NASDAQ` tab. |
| `cautious-trader-verdict` | Stress-tests a shortlisted pick against hard vetoes and a 10-point scorecard, and returns BUY, BUY-HALF or NO-BUY. |

### How to run

Prerequisite: finish `SETUP.md`, then pull prices with `python run_daily.py` (set `MARKET=NASDAQ` first for Nasdaq).

**1. Screen a market** (`qsx-stock-aggresive` for TSX, `qsx-nasdaq-aggressive` for Nasdaq)
1. Set the market: leave `MARKET` unset or `TSX`, or `set MARKET=NASDAQ`. Check that the first line of output reads `Market: TSX [screen v2]` or `Market: NASDAQ [screen v2]`.
2. Ask Claude to run the skill, e.g. `/qsx-stock-aggresive`. It runs `python run_qsx_aggresive.py`, which scores the universe and applies the hard gates (score, ATR range, signal-day rule).
3. Claude checks each candidate for a catalyst dated within the last 3 trading days, drops names without one, and writes the final CSV.
4. Claude runs `python write_list_agg.py <final csv>`, which validates every row and appends to the results sheet. A write only counts as done if the script prints "Appended".
5. Read the report: shortlist with catalysts, regime line (size down if the index is below its 10-day average), and the trailing hit rate of the last 20 picks.

**2. Get a verdict on a pick** (`cautious-trader-verdict`, optional)
1. Give Claude the ticker with its thesis, entry, stop and ATR%, e.g. `/cautious-trader-verdict` plus a row from the shortlist.
2. Claude researches the name, checks the seven vetoes, scores the five factors out of 10, and returns BUY (8-10), BUY-HALF (5-7) or NO-BUY (0-4) with sources.



## Weekly cleanup: sheet retention

`cleanup_list_agg_v2.py` trims two unrelated sources of unbounded growth in
one weekly run:

- **`List_agg` / `List_agg_NASDAQ`.** Every run of `/qtrade-daily-tsx`,
  `/qsx-stock-aggresive` and `/qsx-nasdaq-aggressive` appends a new
  timestamped block (see `write_list_agg.py`) -- nothing trims it on its
  own. Any run-block older than **8 weeks** is dropped entirely (the
  whole block -- header line, column header, and data rows -- never a
  partial row). Runs against both the current results sheet
  (`GOOGLE_OUTPUT_SHEET_ID`) and the original OHLCV sheet
  (`GOOGLE_SHEET_ID`), since the latter still has legacy rows from
  before the write-path fix and should stay trimmed too in case
  anything is ever misrouted there again.
- **`Index_Daily` / `Index_Daily_NASDAQ` / `Universe_OHLCV` /
  `Universe_OHLCV_NASDAQ`.** `run_daily.py` appends a new row per ticker
  per trading day forever, with no dedup and nothing removing old dates
  (see "Known simplifications" below) -- so these grow by however long
  you've been running the pipeline, not by anything useful. The scoring
  logic only ever looks back 20 trading days, so anything older than
  that is pure bloat. Trimmed to the last **90 calendar days** by date,
  keeping the header row and dropping only rows whose date falls
  outside the window.

Run it manually any time with:
```bash
python cleanup_list_agg_v2.py
```

## Troubleshooting

**`AUTH FAILED: Token refresh failed (400): ...`**
Your stored refresh token is stale, expired (eg: 7 days unused), or was
already consumed by another run. Generate a new manual authorization
token in the Brokerage API Centre and reseed `token_store.json` as in
step 2 above.

**`WARN: no symbolId found for X`**
The ticker in your universe CSV doesn't match what `symbols/search`
returns. Try the ticker without a suffix, or check the exact symbol
string on Questrade's site. For Nasdaq specifically, this may also mean
the symbol uses a naming convention the prefix-search fallback wasn't
written for yet (see "Also unverified" above).
