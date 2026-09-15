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
