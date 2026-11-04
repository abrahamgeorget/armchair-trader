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
   -- the raw price tabs. Each is rewritten to hold, per ticker, only
   the most recent OHLCV_RETAIN_SESSIONS (65) trading days, one row per
   (ticker, date):
     * duplicate (ticker, date) rows are collapsed to the LAST occurrence
       (the most recent pull), the same rule the screens use. Before the
       Nov 2026 run_daily.py upsert fix, every daily run re-appended its
       ~10-day lookback, so each session appeared ~7 times;
     * per ticker, only the newest 65 distinct dates are kept. 65 = the
       60-session history the screens require (run_qsx_aggresive's
       filter, the 50-day SMA regime gate, ATR14, 20-day highs/volume)
       plus a 5-session buffer. Going lower makes the screens skip
       tickers;
     * tickers whose newest bar is more than STALE_TICKER_DAYS (30)
       calendar days older than the tab's newest bar are dropped -- they
       stopped trading (delisted, merged, moved exchange) and the screens
       already exclude them;
     * rows with a missing/unparseable date are kept, not guessed at.
   After rewriting, the tab's grid is shrunk to the rows written.
   Clearing cells alone doesn't free them: empty grid rows still count
   toward Google Sheets' 10-million-cell limit per spreadsheet.

Safety: before any price tab is rewritten, its current contents are
saved to backups/<tab>_<timestamp>.csv next to this script (the newest 3
per tab are kept; add backups/ to .gitignore). The new rows
are written over the top of the tab in batches, then the leftover rows
below are removed, so the tab is never empty mid-run. If a run fails
part-way, the backup CSV has everything (see restore note it prints).

Usage:

    python cleanup_list_agg.py            # clean everything
    python cleanup_list_agg.py --dry-run  # print before/after counts, change nothing

Meant to run weekly and unattended (cleanup_weekly.bat via Windows Task
Scheduler, or a scheduled GitHub Actions job). Safe to run any time: it
is idempotent.
"""

import csv
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
from sheets_writer import get_client

LIST_AGG_RETENTION_DAYS = 56   # 8 weeks
OHLCV_RETAIN_SESSIONS = 65     # trading days kept per ticker (screens need 60)
STALE_TICKER_DAYS = 30         # drop tickers with no bar in this many calendar days
WRITE_BATCH_ROWS = 20_000      # rows per Sheets API write
BACKUPS_KEPT = 3               # newest backup CSVs kept per tab

HERE = Path(__file__).resolve().parent
BACKUP_DIR = HERE / "backups"
RUN_LINE_RE = re.compile(r"^Run:\s*(\d{4}-\d{2}-\d{2})")

# (sheet_id, tab_name, label) -- List_agg* tabs, cleaned by run-block.
LIST_AGG_TARGETS = [
    (config.GOOGLE_OUTPUT_SHEET_ID, "List_agg", "results sheet / List_agg"),
    (config.GOOGLE_OUTPUT_SHEET_ID, "List_agg_NASDAQ", "results sheet / List_agg_NASDAQ"),
    (config.GOOGLE_SHEET_ID, "List_agg", "ORIGINAL sheet / List_agg (legacy)"),
    (config.GOOGLE_SHEET_ID, "List_agg_NASDAQ", "ORIGINAL sheet / List_agg_NASDAQ (legacy)"),
]

# (sheet_id, tab_name, label) -- raw OHLCV tabs, trimmed per ticker.
# All four live in the one raw-pull sheet (config.GOOGLE_SHEET_ID).
OHLCV_TARGETS = [
    (config.GOOGLE_SHEET_ID, "Index_Daily", "Index_Daily (TSX)"),
    (config.GOOGLE_SHEET_ID, "Universe_OHLCV", "Universe_OHLCV (TSX)"),
    (config.GOOGLE_SHEET_ID, "Index_Daily_NASDAQ", "Index_Daily_NASDAQ"),
    (config.GOOGLE_SHEET_ID, "Universe_OHLCV_NASDAQ", "Universe_OHLCV_NASDAQ"),
]


# --- sheet helpers -------------------------------------------------------------

def rewrite_tab(ws, new_rows, ncols):
    """
    Write new_rows over the top of the tab in batches, then delete every
    grid row below them. The tab is never blank mid-run, and the grid ends
    exactly len(new_rows) rows tall, which is what frees the cells.
    """
    padded = [list(r) + [""] * (ncols - len(r)) for r in new_rows]
    for start in range(0, len(padded), WRITE_BATCH_ROWS):
        chunk = padded[start:start + WRITE_BATCH_ROWS]
        ws.update(range_name=f"A{start + 1}", values=chunk, value_input_option="RAW")
    # Keep at least 2 rows: Sheets refuses to delete every non-frozen row,
    # which a 1-row resize would do on a tab with a frozen header.
    ws.resize(rows=max(len(padded), 2))


def backup_tab(tab_name, rows):
    """Save the tab to backups/<tab>_<timestamp>.csv; keep only the newest BACKUPS_KEPT per tab."""
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = BACKUP_DIR / f"{tab_name}_{stamp}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    old = sorted(BACKUP_DIR.glob(f"{tab_name}_*.csv"))[:-BACKUPS_KEPT]
    for p in old:
        try:
            p.unlink()
        except OSError:
            pass  # e.g. OneDrive has it locked; harmless, try again next week
    return path


# --- List_agg* -------------------------------------------------------------------

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


def clean_list_agg_tab(gc, sheet_id: str, tab_name: str, label: str, cutoff, dry_run=False) -> None:
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
    dropped_dates = ", ".join(sorted({b["run_date"].isoformat() for b in dropped}))
    print(
        f"  [{label}] {'would drop' if dry_run else 'dropped'} {len(dropped)} run-block(s) older than "
        f"{cutoff.isoformat()} (dates: {dropped_dates}) -- {before} rows -> {after} rows."
    )
    if dry_run:
        return

    if new_rows:
        rewrite_tab(ws, new_rows, max(len(r) for r in rows))
    else:
        ws.clear()
        ws.resize(rows=2)


# --- OHLCV tabs ----------------------------------------------------------------------

def _parse_date(raw):
    try:
        return datetime.strptime(str(raw if raw is not None else "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def trim_ohlcv_rows(header, data, keep_sessions=OHLCV_RETAIN_SESSIONS, stale_days=STALE_TICKER_DAYS):
    """
    Pure function (no Sheets I/O). data = rows after the header.
    Returns (kept_rows, stats). kept_rows is sorted by ticker, then date.
    """
    try:
        di = header.index("date")
        ti = header.index("ticker")
    except ValueError:
        di, ti = 0, 1

    latest = {}       # (ticker, date) -> row, last occurrence wins
    undated = []
    for row in data:
        d = _parse_date(row[di] if len(row) > di else "")
        t = str(row[ti] if len(row) > ti else "").strip()
        if d is None or not t:
            undated.append(row)
            continue
        latest[(t, d)] = row

    by_ticker = {}
    for (t, d), row in latest.items():
        by_ticker.setdefault(t, []).append((d, row))

    tab_latest = max((d for (_, d) in latest), default=None)
    stale_cutoff = tab_latest - timedelta(days=stale_days) if tab_latest else None

    kept, stale = [], []
    trimmed_dates = 0
    for t in sorted(by_ticker):
        bars = sorted(by_ticker[t], key=lambda x: x[0])
        if stale_cutoff and bars[-1][0] < stale_cutoff:
            stale.append(f"{t} (last {bars[-1][0].isoformat()})")
            continue
        trimmed_dates += max(0, len(bars) - keep_sessions)
        kept.extend(row for _, row in bars[-keep_sessions:])

    stats = {
        "rows_before": len(data),
        "unique_before": len(latest),
        "duplicates_removed": len(data) - len(undated) - len(latest),
        "old_sessions_removed": trimmed_dates,
        "stale_tickers": stale,
        "undated_kept": len(undated),
        "rows_after": len(kept) + len(undated),
        "tickers_kept": len(by_ticker) - len(stale),
    }
    return kept + undated, stats


def clean_ohlcv_tab(gc, sheet_id: str, tab_name: str, label: str, dry_run=False) -> None:
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except Exception:
        print(f"  [{label}] tab not found, skipping.")
        return

    # UNFORMATTED_VALUE: numbers come back as numbers, so the RAW rewrite
    # stores them as numbers again. The default (formatted) read returns
    # strings, and writing those back RAW would turn every price into text.
    rows = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    if len(rows) <= 1:
        print(f"  [{label}] empty, nothing to do.")
        return

    header, data = rows[0], rows[1:]
    kept, s = trim_ohlcv_rows(header, data)
    grid_rows, grid_cols = ws.row_count, ws.col_count
    summary = (
        f"  [{label}] {s['rows_before']:,} rows ({grid_rows:,} grid rows x {grid_cols} cols) -> {s['rows_after']:,} rows | "
        f"{s['duplicates_removed']:,} duplicates, {s['old_sessions_removed']:,} sessions beyond "
        f"{OHLCV_RETAIN_SESSIONS} per ticker, {len(s['stale_tickers'])} stale ticker(s) removed; "
        f"{s['tickers_kept']} tickers kept"
    )
    if s["rows_after"] == s["rows_before"] and grid_rows == s["rows_before"] + 1:
        print(f"  [{label}] {s['rows_before']:,} rows, {s['tickers_kept']} tickers -- already trimmed, nothing to do.")
        return
    print(summary)
    if s["stale_tickers"]:
        print(f"      stale: {', '.join(s['stale_tickers'])}")
    if dry_run:
        return

    path = backup_tab(tab_name, rows)
    print(f"      backup: {path}")
    try:
        rewrite_tab(ws, [header] + kept, max(len(r) for r in rows))
    except Exception as e:
        print(f"      REWRITE FAILED: {e}\n      The tab may be part-written. Restore by importing {path} "
              f"into '{tab_name}' (File > Import > Replace current sheet), then rerun.")
        raise
    print(f"      rewritten: {len(kept) + 1:,} rows incl. header; grid shrunk to match.")


def main():
    dry_run = "--dry-run" in sys.argv[1:]
    now = datetime.now(timezone.utc)
    list_agg_cutoff = (now - timedelta(days=LIST_AGG_RETENTION_DAYS)).date()

    gc = get_client(config.GOOGLE_SERVICE_ACCOUNT_PATH)
    if dry_run:
        print("DRY RUN -- nothing will be changed.")

    print(f"List_agg* retention cutoff: dropping run-blocks older than {list_agg_cutoff.isoformat()} "
          f"({LIST_AGG_RETENTION_DAYS} days / 8 weeks)")
    for sheet_id, tab_name, label in LIST_AGG_TARGETS:
        clean_list_agg_tab(gc, sheet_id, tab_name, label, list_agg_cutoff, dry_run)

    print(f"OHLCV* retention: one row per (ticker, date), newest {OHLCV_RETAIN_SESSIONS} trading days per ticker, "
          f"tickers silent for {STALE_TICKER_DAYS}+ days dropped")
    for sheet_id, tab_name, label in OHLCV_TARGETS:
        clean_ohlcv_tab(gc, sheet_id, tab_name, label, dry_run)

    print("Done.")


if __name__ == "__main__":
    main()
