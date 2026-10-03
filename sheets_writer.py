"""
Thin wrapper around gspread for writing daily rows into named tabs.

For this manual/daily-run version we keep it simple: each run appends
its rows. If you rerun on the same day, you'll get duplicate rows for
that date -- dedup logic (delete-then-write for today's date) is a
natural next step once this is running on a schedule, and is deliberately
left out here to keep a first working version simple.
"""

from google.oauth2.service_account import Credentials
import gspread

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_client(service_account_path: str):
    creds = Credentials.from_service_account_file(service_account_path, scopes=SCOPES)
    return gspread.authorize(creds)


def write_rows(client, sheet_id: str, tab_name: str, header: list[str], rows: list[list]):
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=2000, cols=max(len(header), 1) + 2)

    existing = ws.get_all_values()
    if not existing:
        ws.append_row(header, value_input_option="RAW")

    if rows:
        ws.append_rows(rows, value_input_option="RAW")

    print(f"Wrote {len(rows)} rows to '{tab_name}'.")


def write_table_overwrite(client, sheet_id: str, tab_name: str, header: list[str], rows: list[list], run_timestamp: str):
    """
    Clears the tab and writes only the latest run's results, unlike
    write_table_append which keeps a running history. Used by the
    aggressive-screen write_list_agg.py so each market's List_agg tab
    always reflects just the most recent run.
    """
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=2000, cols=max(len(header), 1) + 2)

    ws.append_row([f"Run: {run_timestamp}"], value_input_option="RAW")
    ws.append_row(header, value_input_option="RAW")
    if rows:
        ws.append_rows(rows, value_input_option="RAW")

    print(f"Overwrote '{tab_name}' with {len(rows)} rows (run: {run_timestamp}).")


def write_table_append(client, sheet_id: str, tab_name: str, header: list[str], rows: list[list], run_timestamp: str):
    """
    Appends a timestamped batch of results without clearing earlier entries.
    This is the desired behavior for List_agg, which should keep a historical
    record of each run alongside the shortlisted stocks.
    """
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=2000, cols=max(len(header), 1) + 2)

    ws.append_row([f"Run: {run_timestamp}"], value_input_option="RAW")
    ws.append_row(header, value_input_option="RAW")
    if rows:
        ws.append_rows(rows, value_input_option="RAW")

    print(f"Appended '{tab_name}' with {len(rows)} rows (run: {run_timestamp}).")
