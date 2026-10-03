"""
One-time helper: wipe Universe_OHLCV and Index_Daily before re-running the
140-day backfill with the corrected run_daily.py (start-date fix).

Run once with:
    python clear_before_backfill.py

Safe to delete after you've used it.
"""

import config
from sheets_writer import get_client

TABS_TO_CLEAR = ["Universe_OHLCV", "Index_Daily"]


def main():
    gc = get_client(config.GOOGLE_SERVICE_ACCOUNT_PATH)
    sh = gc.open_by_key(config.GOOGLE_SHEET_ID)

    for tab_name in TABS_TO_CLEAR:
        ws = sh.worksheet(tab_name)
        ws.clear()
        print(f"Cleared '{tab_name}'.")

    print("Done. Now run the backfill, e.g.:")
    print('  $env:QT_LOOKBACK_DAYS = "140"; python run_daily.py   (PowerShell)')
    print("  set QT_LOOKBACK_DAYS=140 && python run_daily.py      (cmd)")


if __name__ == "__main__":
    main()
