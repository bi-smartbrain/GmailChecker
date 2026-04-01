import os

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials


def main() -> int:
    dotenv_path = os.getenv("DOTENV_PATH", r"C:\Rubrain\Secrets\.env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)

    sa_path = os.getenv("GOOGLE_SHEETS_SA_JSON_PATH", r"C:\Rubrain\Secrets\service_account.json")
    spreadsheet_url = os.getenv("SPREADSHEET_URL")
    worksheet_title = os.getenv("WORKSHEET")
    if not spreadsheet_url or not worksheet_title:
        print("Set SPREADSHEET_URL and WORKSHEET")
        return 2

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(sa_path, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_url(spreadsheet_url)
    ws = sh.worksheet(worksheet_title)

    values = ws.get_all_values()
    print(f"Worksheet: {worksheet_title}")
    print(f"Rows with values: {len(values)}")
    for r in values[:5]:
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
