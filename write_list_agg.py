"""
Writes the qsx-stock-aggresive (or qsx-nasdaq-aggressive) skill's final
candidate table into a tab of Abe's RESULTS-TRACKING sheet
(config.GOOGLE_OUTPUT_SHEET_ID) -- a separate spreadsheet from
config.GOOGLE_SHEET_ID, which holds the raw daily OHLCV pull. Each run is
APPENDED as a new timestamped block ("Run: <when>" + header + rows)
rather than clearing the tab first, so the tab accumulates a history of
every run's recommendations instead of only ever showing the latest one.
Which tab depends on config.MARKET -- "List_agg" for TSX (default),
"List_agg_NASDAQ" if MARKET=NASDAQ is set -- so TSX and Nasdaq results
never land in the same table. Keep MARKET consistent with whichever run
produced the candidates CSV you're passing in.

This is a separate script (not part of run_daily.py) because it's meant
to run at the END of an aggressive-screen analysis -- after scoring,
gating, and catalyst verification have already produced a candidate
list -- not as part of the daily OHLCV pull.

Usage: python write_list_agg.py candidates.csv

Expects a CSV with columns:
  ticker, score, atr_pct, entry, target, stop, shares, target_upside_pct,
  catalyst, catalyst_url

Claude Code (or Abe, running this after a chat-based analysis) should
write that CSV from the run's results, then call this script.
"""

import csv
import sys
from datetime import datetime, timezone

import config
from sheets_writer import get_client, write_table_append

HEADER = [
    "ticker", "score", "atr_pct", "entry", "target", "stop",
    "shares", "target_upside_pct", "catalyst", "catalyst_url",
]


def load_candidates(path: str) -> list[list]:
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return [[row.get(h, "") for h in HEADER] for row in reader]


def main():
    if len(sys.argv) < 2:
        print("Usage: python write_list_agg.py candidates.csv", file=sys.stderr)
        sys.exit(1)

    rows = load_candidates(sys.argv[1])
    gc = get_client(config.GOOGLE_SERVICE_ACCOUNT_PATH)
    run_ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")

    print(f"Market: {config.MARKET}  (appending to tab '{config.LIST_AGG_TAB}' "
          f"in results sheet {config.GOOGLE_OUTPUT_SHEET_ID})")
    write_table_append(gc, config.GOOGLE_OUTPUT_SHEET_ID, config.LIST_AGG_TAB, HEADER, rows, run_ts)


if __name__ == "__main__":
    main()
