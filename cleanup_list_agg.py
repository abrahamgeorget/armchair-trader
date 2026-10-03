"""
Weekly retention cleanup for this project's Google Sheets tabs.

Two unrelated kinds of unbounded growth, both handled here:

1. List_agg / List_agg_NASDAQ -- both aggressive-screen skills
   (qsx-stock-aggresive, qsx-nasdaq-aggressive) append a full timestamped
   block ("Run: <when>" + header + rows) every time they run (see
   write_list_agg.py / sheets_writer.write_table_append). Any run-block
   whose "Run: <date> ..." line is older than LIST_AGG_RETENTION_DAYS
   (8 weeks) is dropped entirely -- the whole block, never a partial
   row. Runs against four targets: List_agg and List_agg_NASDAQ in both
   the current results-tracking sheet (config.GOOGLE_OUTPUT_SHEET_ID,
   where every run lands now) and the ORIGINAL OHLCV sheet
   (config.GOOGLE_SHEET_ID, which still holds legacy rows from before
   the write-path fix and should stay trimmed as a safety net).

2. Index_Daily / Index_Daily_NASDAQ / Universe_OHLCV / Universe_OHLCV_NASDAQ
   -- run_daily.py appends a new row per ticker per trading day, every
   day, with no dedup and nothing ever removing old dates (see
   sheets_writer.write_rows). The scoring logic in qsx_stock_aggresive.py
   only ever looks back 20 trading days (20-day median volume, 20-day
   return, 20-day high; ATR uses 14), so anything older than that is
   pure bloat -- here trimmed to OHLCV_RETENTION_DAYS (90 calendar days,
   a safety margin above the 20-trading-day need) by date, keeping the
   header row and any row whose "date" column falls within the window.

Meant to run weekly and unattended via Windows Task Scheduler:

    python cleanup_list_agg.py

Safe to run manually any time -- it's idempotent (nothing older than the
relevant window means nothing changes) and only ever removes whole
run-blocks (List_agg*) or whole dated rows (OHLCV*) older than their
cutoff, never anything from the current window.
"""

import re
from datetime import datetime, timedelta, timezone

import config
from sheets_writer import get_client

LIST_AGG_RETENTION_DAYS = 56  # 8 weeks
OHLCV_RETENTION_DAYS = 90  # ~60 trading days -- scoring only needs 20

RUN_LINE_RE = re.compile(r"^Run:\s*(\d{4}-\d{2}-\d{2})")

# (sheet_id, tab_name, label) -- List_agg* tabs, cleaned by run-block.
LIST_AGG_TARGETS = [
    (config.GOOGLE_OUTPUT_SHEET_ID, "List_agg", "results sheet / List_agg"),
    (config.GOOGLE_OUTPUT_SHEET_ID, "List_agg_NASDAQ", "results sheet / List_agg_NASDAQ"),
    (config.GOOGLE_SHEET_ID, "List_agg", "ORIGINAL sheet / List_agg (legacy)"),
    (config.GOOGLE_SHEET_ID, "List_agg_NASDAQ", "ORIGINAL sheet / List_agg_NASDAQ (legacy)"),
]

# (sheet_id, tab_name, label) -- raw OHLCV tabs, cleaned by date column.
# All four live in the one raw-pull sheet (config.GOOGLE_SHEET_ID), per
# run_daily.py / README.md -- not the results-tracking sheet.
OHLCV_TARGETS = [
    (config.GOOGLE_SHEET_ID, "Index_Daily", "Index_Daily (TSX)"),
    (config.GOOGLE_SHEET_ID, "Universe_OHLCV", "Universe_OHLCV (TSX)"),
    (config.GOOGLE_SHEET_ID, "Index_Daily_NASDAQ", "Index_Daily_NASDAQ"),
    (config.GOOGLE_SHEET_ID, "Universe_OHLCV_NASDAQ", "Universe_OHLCV_NASDAQ"),
]


def parse_blocks(rows: list[list[str]]) -> list[dict]:
    """
    Split a tab's raw rows into run-blocks. Each block is
    {"run_date": date or None, "rows": [[...], ...]} where rows[0] is
    the "Run: ..." line, rows[1] is the column header, and the rest are
    that run's data rows.

    Rows found before the first "Run:" line (shouldn't normally happen,
    but tabs are hand-editable) are kept together as a dateless block,
    and a dateless block is NEVER dropped -- we don't guess at the age
    of something we can't date.
    """
    blocks = []
    current = None
    for row in rows:
        first_cell = row[0] if row else ""
        m = RUN_LINE_RE.match(first_cell.strip()) if isinstance(first_cell, str) else None
        if m:
            if current is not None:
                blocks.append(current)
            run_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            current = {"run_date": run_date, "rows": [row]}
        else:
            if current is None:
                current = {"run_date": None, "rows": []}
            current["rows"].append(row)
    if current is not None:
        blocks.append(current)
    return blocks


def clean_list_agg_tab(gc, sheet_id: str, tab_name: str, label: str, cutoff) -> None:
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except Exception:
        print(f"  [{label}] tab not found, skipping.")
        return

    rows = ws.get_all_values()
    if not rows:
        print(f"  [{label}] empty, nothing to do.")
        return

    blocks = parse_blocks(rows)
    kept, dropped = [], []
    for b in blocks:
        if b["run_date"] is None or b["run_date"] >= cutoff:
            kept.append(b)
        else:
            dropped.append(b)

    if not dropped:
        print(f"  [{label}] {len(blocks)} run-block(s), all within {LIST_AGG_RETENTION_DAYS}d -- nothing to trim.")
        return

    new_rows = [row for b in kept for row in b["rows"]]
    before = sum(len(b["rows"]) for b in blocks)
    after = len(new_rows)

    # Full rewrite: clear the tab, then write back only the kept blocks.
    # This is a deliberate retention trim, not the per-run append path --
    # write_list_agg.py / write_table_append are untouched by this script.
    ws.clear()
    if new_rows:
        ws.update(range_name="A1", values=new_rows, value_input_option="RAW")

    dropped_dates = ", ".join(sorted({b["run_date"].isoformat() for b in dropped}))
    print(
        f"  [{label}] dropped {len(dropped)} run-block(s) older than {cutoff.isoformat()} "
        f"(dates: {dropped_dates}) -- {before} rows -> {after} rows."
    )


def clean_ohlcv_tab(gc, sheet_id: str, tab_name: str, label: str, cutoff) -> None:
    """
    Date-column trim for a plain append-only OHLCV tab: keep the header
    row plus any data row whose "date" column (column A, YYYY-MM-DD) is
    on or after cutoff. A row with a missing/unparseable date is kept,
    not guessed at.
    """
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except Exception:
        print(f"  [{label}] tab not found, skipping.")
        return

    rows = ws.get_all_values()
    if not rows:
        print(f"  [{label}] empty, nothing to do.")
        return

    header, data = rows[0], rows[1:]
    kept, dropped_dates = [], set()
    for row in data:
        raw_date = (row[0] if row else "").strip()
        try:
            row_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
        except ValueError:
            kept.append(row)  # can't date it, don't guess -- keep it
            continue
        if row_date >= cutoff:
            kept.append(row)
        else:
            dropped_dates.add(raw_date[:10])

    if not dropped_dates:
        print(f"  [{label}] {len(data)} row(s), all within {OHLCV_RETENTION_DAYS}d -- nothing to trim.")
        return

    new_rows = [header] + kept
    ws.clear()
    ws.update(range_name="A1", values=new_rows, value_input_option="RAW")

    oldest_dropped = min(dropped_dates)
    newest_dropped = max(dropped_dates)
    print(
        f"  [{label}] dropped rows for {len(dropped_dates)} date(s) older than {cutoff.isoformat()} "
        f"({oldest_dropped} .. {newest_dropped}) -- {len(data)} rows -> {len(kept)} rows."
    )


def main():
    now = datetime.now(timezone.utc)
    list_agg_cutoff = (now - timedelta(days=LIST_AGG_RETENTION_DAYS)).date()
    ohlcv_cutoff = (now - timedelta(days=OHLCV_RETENTION_DAYS)).date()

    gc = get_client(config.GOOGLE_SERVICE_ACCOUNT_PATH)

    print(f"List_agg* retention cutoff: dropping run-blocks older than {list_agg_cutoff.isoformat()} "
          f"({LIST_AGG_RETENTION_DAYS} days / 8 weeks)")
    for sheet_id, tab_name, label in LIST_AGG_TARGETS:
        clean_list_agg_tab(gc, sheet_id, tab_name, label, list_agg_cutoff)

    print(f"OHLCV* retention cutoff: dropping dated rows older than {ohlcv_cutoff.isoformat()} "
          f"({OHLCV_RETENTION_DAYS} days)")
    for sheet_id, tab_name, label in OHLCV_TARGETS:
        clean_ohlcv_tab(gc, sheet_id, tab_name, label, ohlcv_cutoff)

    print("Done.")


if __name__ == "__main__":
    main()
