import os
from datetime import datetime, timezone

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials


MAILBOX_HEADERS = [
    "mailbox",
    "enabled",
    "subject_phrase",
    "gmail_query_base",
    "tg_chat_id",
    "tags_string",
    "last_internal_ms",
    "last_sent_ids_json",
    "updated_at_utc",
    "notes",
]


EVENT_HEADERS = [
    "ts_utc",
    "level",
    "source",
    "mailbox",
    "action",
    "gmail_message_id",
    "internal_ms",
    "from",
    "subject",
    "preview",
    "tg_chat_id",
    "tg_message_id",
    "error",
]


def main() -> int:
    dotenv_path = os.getenv("DOTENV_PATH", r"C:\Rubrain\Secrets\.env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)

    sa_path = os.getenv("GOOGLE_SHEETS_SA_JSON_PATH", r"C:\Rubrain\Secrets\service_account.json")
    if not os.path.exists(sa_path):
        print(f"Service account JSON not found: {sa_path}")
        return 2

    spreadsheet_url = os.getenv("SPREADSHEET_URL", "https://docs.google.com/spreadsheets/d/1SS5RanpLrtGHfHgePqWSDRm-57XSRK5TKNecc4FYUfI/edit")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(sa_path, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_url(spreadsheet_url)

    titles = [ws.title for ws in sh.worksheets()]
    print("Existing worksheets:")
    for t in titles:
        print(f"- {t}")

    # User request: delete Sheet1, keep Sheet2.
    if "Sheet1" in titles:
        ws = sh.worksheet("Sheet1")
        sh.del_worksheet(ws)
        print("Deleted worksheet: Sheet1")

    def ensure_sheet(title: str, headers: list[str], rows: int = 2000, cols: int = 20):
        try:
            ws = sh.worksheet(title)
            created = False
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=title, rows=rows, cols=max(cols, len(headers) + 2))
            created = True

        existing = ws.get_all_values()

        def row_empty(r: list[str]) -> bool:
            return all((not (c or "").strip()) for c in r)

        if not existing or all(row_empty(r) for r in existing):
            ws.update("A1", [headers])
            try:
                ws.freeze(rows=1)
            except Exception:
                pass
            print(f"Initialized headers for: {title}")
        else:
            # If the first row doesn't match, insert headers above existing data.
            if existing[0][: len(headers)] != headers:
                ws.insert_row(headers, 1)
                try:
                    ws.freeze(rows=1)
                except Exception:
                    pass
                print(f"Inserted headers for: {title}")

        return ws, created

    mailboxes_ws, _ = ensure_sheet("mailboxes", MAILBOX_HEADERS)
    ensure_sheet("events", EVENT_HEADERS)

    config_headers = ["key", "value", "description"]
    config_ws, _ = ensure_sheet("config", config_headers)

    config_values = config_ws.get_all_values()
    config_keys = {r[0].strip() for r in config_values[1:] if r and r[0].strip()}
    if "TG_ALLOW_NON_PERSONAL" not in config_keys:
        config_ws.append_row(["TG_ALLOW_NON_PERSONAL", "true", "Block group/channel sends unless true"], value_input_option="RAW")
    if "POLL_INTERVAL_SECONDS" not in config_keys:
        config_ws.append_row(["POLL_INTERVAL_SECONDS", "15", "Seconds between polls"], value_input_option="RAW")
    if "BOOTSTRAP" not in config_keys:
        config_ws.append_row(["BOOTSTRAP", "skip_existing", "skip_existing|notify_existing"], value_input_option="RAW")
    if "TG_CHAT_ID_1" not in config_keys:
        config_ws.append_row(["TG_CHAT_ID_1", "302376278", "Personal chat"], value_input_option="RAW")
    if "TG_CHAT_ID_5" not in config_keys:
        config_ws.append_row(["TG_CHAT_ID_5", "302376278", "Support chat"], value_input_option="RAW")
    if "TG_CHAT_ID_6" not in config_keys:
        config_ws.append_row(["TG_CHAT_ID_6", "-5012137290", "Debug group"], value_input_option="RAW")
    print("Seeded config sheet defaults.")

    seed_mailboxes = [
        {
            "email": "info@freelance.kz",
            "subject_phrase": "Новое сообщение на Freelance.kz",
            "gmail_query_base": "in:inbox",
            "tg_chat_id": "302376278",
            "tags_string": "@karyushka @aglaya_smartbrainio @katrinkee @TsaritsaPolei @olya_smartbrain",
        },
        {
            "email": "info@unicheck.ai",
            "subject_phrase": "Новое письмо",
            "gmail_query_base": "in:inbox",
            "tg_chat_id": "302376278",
            "tags_string": "@karyushka",
        },
    ]

    values = mailboxes_ws.get_all_values()
    existing_mailboxes = {r[0].strip().lower() for r in values[1:] if r and len(r) > 0 and r[0].strip()}

    for seed in seed_mailboxes:
        email = seed["email"]
        if email.strip().lower() not in existing_mailboxes:
            now = datetime.now(timezone.utc).isoformat()
            mailboxes_ws.append_row(
                [
                    email,
                    "TRUE",
                    seed["subject_phrase"],
                    seed["gmail_query_base"],
                    seed["tg_chat_id"],
                    seed["tags_string"],
                    "0",
                    "[]",
                    now,
                    "seeded by sheets_setup.py",
                ],
                value_input_option="RAW",
            )
            print(f"Seeded mailbox row: {email}")
        else:
            print(f"Mailbox row already exists: {email}")

    print("Setup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
