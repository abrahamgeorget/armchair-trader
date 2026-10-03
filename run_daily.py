"""
Daily Questrade -> Google Sheet pull. Run manually with:

    python run_daily.py

Set MARKET=NASDAQ (env var) before running to pull the Nasdaq/ONEQ side
instead of the TSX/XIC default -- see config.py for what that switches.

What it does, in order:
  1. Refreshes the Questrade access token (and immediately re-saves the
     new refresh token -- see questrade_client.py for why this matters).
  2. Fetches daily OHLCV candles for the index proxy (config.INDEX_PROXY_TICKER)
     and every ticker in config.UNIVERSE_CSV.
  3. Appends the results into two tabs in your target Google Sheet
     (config.INDEX_TAB / config.UNIVERSE_TAB -- "Index_Daily" /
     "Universe_OHLCV" for TSX, "Index_Daily_NASDAQ" / "Universe_OHLCV_NASDAQ"
     for Nasdaq):
       - <INDEX_TAB>     (date, ticker, open, high, low, close, volume)
       - <UNIVERSE_TAB>  (date, ticker, open, high, low, close, volume)
"""

import csv
import sys

import requests

import config
from questrade_client import QuestradeClient, QuestradeAuthError
from sheets_writer import get_client, write_rows

HEADER = ["date", "ticker", "open", "high", "low", "close", "volume"]


def load_universe(path: str) -> list[str]:
    with open(path) as f:
        return [row["ticker"].strip() for row in csv.DictReader(f) if row["ticker"].strip()]


def candles_to_rows(ticker: str, candles: list[dict]) -> list[list]:
    # Use "start", not "end": Questrade's daily-candle "end" is the *next*
    # calendar day (start + 1 day), so keying off it mislabels every row
    # with tomorrow's date. "start" is the actual trading session date.
    rows = []
    for c in candles:
        rows.append(
            [
                c["start"][:10],  # YYYY-MM-DD
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
    print(f"Market: {config.MARKET}  (index proxy {config.INDEX_PROXY_TICKER}, "
          f"universe {config.UNIVERSE_CSV}, tabs '{config.INDEX_TAB}' / '{config.UNIVERSE_TAB}')")

    qt = QuestradeClient()
    try:
        qt.authenticate()
    except QuestradeAuthError as e:
        print(f"AUTH FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    gc = get_client(config.GOOGLE_SERVICE_ACCOUNT_PATH)

    index_ticker = config.INDEX_PROXY_TICKER
    tickers = load_universe(config.UNIVERSE_CSV)

    # Resolve everything (index proxy + universe) in one batch of exact
    # lookups -- far fewer calls than one prefix search per ticker, and
    # immune to the preferred-share/debenture mismatches prefix search
    # was prone to.
    all_names = [index_ticker] + tickers
    symbol_ids = qt.get_symbol_ids_bulk(all_names)

    # Anything the exact lookup missed gets one fallback attempt via
    # prefix search (loudly logged -- these are worth spot-checking).
    unresolved = [t for t, sid in symbol_ids.items() if sid is None]
    for t in unresolved:
        print(f"  no exact match for {t}, trying prefix search fallback...")
        symbol_ids[t] = qt.get_symbol_id_by_prefix(t)

    # --- index proxy ---
    index_id = symbol_ids.get(index_ticker)
    if index_id is None:
        print(f"WARN: could not resolve symbolId for index proxy {index_ticker}")
    else:
        try:
            candles = qt.get_daily_candles(index_id, lookback_days=config.QT_LOOKBACK_DAYS)
            write_rows(gc, config.GOOGLE_SHEET_ID, config.INDEX_TAB, HEADER, candles_to_rows(index_ticker, candles))
        except requests.exceptions.RequestException as e:
            print(f"WARN: candles request failed for index proxy {index_ticker} (symbolId={index_id}): {e}")

    # --- universe ---
    # Catch RequestException (not just HTTPError) so a transient network
    # blip -- a dropped SSL connection, a timeout, anything short of a
    # clean HTTP error -- skips that one ticker instead of crashing the
    # whole script and losing every row already fetched for the tickers
    # before it (all_rows only gets written to the Sheet once, at the end).
    all_rows = []
    for t in tickers:
        sid = symbol_ids.get(t)
        if sid is None:
            print(f"WARN: no symbolId found for {t}, skipping")
            continue
        try:
            candles = qt.get_daily_candles(sid, lookback_days=config.QT_LOOKBACK_DAYS)
        except requests.exceptions.RequestException as e:
            print(f"WARN: candles request failed for {t} (symbolId={sid}): {e}")
            continue
        all_rows.extend(candles_to_rows(t, candles))

    write_rows(gc, config.GOOGLE_SHEET_ID, config.UNIVERSE_TAB, HEADER, all_rows)

    print("Done.")


if __name__ == "__main__":
    main()
