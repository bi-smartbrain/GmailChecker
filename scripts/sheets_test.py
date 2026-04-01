import os
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv


def main() -> int:
    # Load shared Secrets env if present.
    dotenv_path = os.getenv("DOTENV_PATH", r"C:\Rubrain\Secrets\.env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)

    # Use the "other" (known-working) Sheets service account.
    sa_path = os.getenv("GOOGLE_SHEETS_SA_JSON_PATH", r"C:\Rubrain\Secrets\service_account.json")
    if not os.path.exists(sa_path):
        print(f"Service account JSON not found: {sa_path}")
        return 2

    spreadsheet_url = os.getenv("SPREADSHEET_URL")
    if not spreadsheet_url:
        print("Missing SPREADSHEET_URL in env")
        return 2

    worksheet_title = os.getenv("WORKSHEET", "Sheet1")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(sa_path, scopes=scopes)
    gc = gspread.authorize(creds)

    sh = gc.open_by_url(spreadsheet_url)
    try:
        ws = sh.worksheet(worksheet_title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet_title, rows=1000, cols=20)

    ts = datetime.now(timezone.utc).isoformat()
    row = [ts, "gmailchecker", "hello from sheets_test.py"]
    ws.append_row(row, value_input_option="RAW")
    print(f"Appended row to '{worksheet_title}': {row}")

    values = ws.get_all_values()
    print(f"Total rows now: {len(values)}")
    print("Last 5 rows:")
    for r in values[-5:]:
        print(r)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
