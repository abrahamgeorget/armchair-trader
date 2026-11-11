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
  3. Upserts the results into two tabs in your target Google Sheet
     (config.INDEX_TAB / config.UNIVERSE_TAB -- "Index_Daily" /
     "Universe_OHLCV" for TSX, "Index_Daily_NASDAQ" / "Universe_OHLCV_NASDAQ"
     for Nasdaq):
       - <INDEX_TAB>     (date, ticker, open, high, low, close, volume)
       - <UNIVERSE_TAB>  (date, ticker, open, high, low, close, volume)

Upsert, not append (Nov 2026): each run re-pulls a ~10-day lookback, and
the old append-only write stored every session ~7 times. Now a candle
whose (ticker, date) is already in the tab is skipped if its values are
unchanged, or updated in place if they changed (e.g. a partial bar from
a mid-session run). Only genuinely new (ticker, date) pairs are appended.
cleanup_list_agg.py collapses any duplicates already in the sheet and
keeps the newest 65 trading days per ticker.
"""

import csv
import sys

import gspread
import requests

import config
from questrade_client import QuestradeClient, QuestradeAuthError
from sheets_writer import get_client

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


def _same(a, b) -> bool:
    """Compare a sheet cell (string, maybe formatted) with a candle value."""
    try:
        return abs(float(str(a).replace(",", "")) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def plan_upsert(existing: list[list], new_rows: list[list]):
    """
    Pure function (no Sheets I/O). existing = the tab's values incl. header
    row; new_rows = [date, ticker, open, high, low, close, volume] rows.
    Returns (to_append, to_update, unchanged) where to_update is a list of
    (sheet_row_number, row). If a (ticker, date) appears more than once in
    the tab (legacy duplicates), the LAST occurrence is the one updated --
    the same row the screens read.
    """
    where = {}
    for i, r in enumerate(existing[1:], start=2):  # sheet row numbers; row 1 = header
        if len(r) >= 2 and r[0] != "" and r[1] != "":
            where[(str(r[1]).strip(), str(r[0]).strip()[:10])] = (i, r)
    to_append, to_update, unchanged = [], [], 0
    seen = set()
    for row in new_rows:
        key = (str(row[1]).strip(), str(row[0]).strip()[:10])
        if key in seen:
            continue  # the same candle twice in one pull
        seen.add(key)
        hit = where.get(key)
        if hit is None:
            to_append.append(row)
        elif all(_same(a, b) for a, b in zip(hit[1][2:7], row[2:7])) and len(hit[1]) >= 7:
            unchanged += 1
        else:
            to_update.append((hit[0], row))
    return to_append, to_update, unchanged


def upsert_rows(client, sheet_id: str, tab_name: str, header: list[str], rows: list[list]):
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=2000, cols=len(header))

    # Unformatted, so prices compare exactly instead of against display-rounded text.
    existing = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    if not existing:
        ws.append_row(header, value_input_option="RAW")
        existing = [header]

    to_append, to_update, unchanged = plan_upsert(existing, rows)
    if to_update:
        ws.batch_update(
            [{"range": f"A{n}:G{n}", "values": [r]} for n, r in to_update],
            value_input_option="RAW",
        )
    if to_append:
        ws.append_rows(to_append, value_input_option="RAW")
    print(f"'{tab_name}': {len(to_append)} new rows appended, {len(to_update)} updated in place, "
          f"{unchanged} already present (skipped).")


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
            upsert_rows(gc, config.GOOGLE_SHEET_ID, config.INDEX_TAB, HEADER, candles_to_rows(index_ticker, candles))
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

    upsert_rows(gc, config.GOOGLE_SHEET_ID, config.UNIVERSE_TAB, HEADER, all_rows)

    print("Done.")


if __name__ == "__main__":
    main()
