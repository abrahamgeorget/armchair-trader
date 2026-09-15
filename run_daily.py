"""
Daily Questrade -> Google Sheet pull. Run manually with:

    python run_daily.py

What it does, in order:
  1. Refreshes the Questrade access token (and immediately re-saves the
     new refresh token -- see questrade_client.py for why this matters).
  2. Fetches daily OHLCV candles for the index proxy (config.INDEX_PROXY_TICKER)
     and every ticker in universe.csv.
  3. Appends the results into two tabs in your target Google Sheet:
       - Index_Daily     (date, ticker, open, high, low, close, volume)
       - Universe_OHLCV  (date, ticker, open, high, low, close, volume)
"""

import csv
import sys

import config
from questrade_client import QuestradeClient, QuestradeAuthError
from sheets_writer import get_client, write_rows

HEADER = ["date", "ticker", "open", "high", "low", "close", "volume"]


def load_universe(path: str) -> list[str]:
    with open(path) as f:
        return [row["ticker"].strip() for row in csv.DictReader(f) if row["ticker"].strip()]


def candles_to_rows(ticker: str, candles: list[dict]) -> list[list]:
    rows = []
    for c in candles:
        rows.append(
            [
                c["end"][:10],  # YYYY-MM-DD
                ticker,
                c["open"],
                c["high"],
                c["low"],
                c["close"],
                c["volume"],
            ]
        )
    return rows


def main():
    qt = QuestradeClient()
    try:
        qt.authenticate()
    except QuestradeAuthError as e:
        print(f"AUTH FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    gc = get_client(config.GOOGLE_SERVICE_ACCOUNT_PATH)

    # --- index proxy ---
    index_ticker = config.INDEX_PROXY_TICKER
    index_id = qt.get_symbol_id(index_ticker)
    if index_id is None:
        print(f"WARN: could not resolve symbolId for index proxy {index_ticker}")
    else:
        candles = qt.get_daily_candles(index_id, lookback_days=10)
        write_rows(gc, config.GOOGLE_SHEET_ID, "Index_Daily", HEADER, candles_to_rows(index_ticker, candles))

    # --- universe ---
    tickers = load_universe(config.UNIVERSE_CSV)
    all_rows = []
    for t in tickers:
        sid = qt.get_symbol_id(t)
        if sid is None:
            print(f"WARN: no symbolId found for {t}, skipping")
            continue
        candles = qt.get_daily_candles(sid, lookback_days=10)
        all_rows.extend(candles_to_rows(t, candles))

    write_rows(gc, config.GOOGLE_SHEET_ID, "Universe_OHLCV", HEADER, all_rows)

    print("Done.")


if __name__ == "__main__":
    main()
