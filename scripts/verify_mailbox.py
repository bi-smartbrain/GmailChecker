"""
Verification script: reads setup, mailboxes, and config sheets to validate
new mailbox entries and check for common issues.
"""
import json
import os
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv(r"C:\Rubrain\Secrets\.env")

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1SS5RanpLrtGHfHgePqWSDRm-57XSRK5TKNecc4FYUfI/edit"
SA_PATH = os.getenv("GOOGLE_SHEETS_SA_JSON_PATH", r"C:\Rubrain\Secrets\service_account.json")

def get_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(SA_PATH, scopes=scopes)
    return gspread.authorize(creds)

def strip_float(val: str) -> str:
    if val.endswith(".0"):
        return val[:-2]
    return val

def main():
    gc = get_client()
    sh = gc.open_by_url(SPREADSHEET_URL)

    print("=" * 80)
    print("SETUP SHEET")
    print("=" * 80)
    try:
        ws = sh.worksheet("setup")
        values = ws.get_all_values()
        if not values:
            print("  EMPTY")
        else:
            headers = [h.strip().lower() for h in values[0]]
            print(f"  Headers: {headers}")
            col_map = {h: i for i, h in enumerate(headers)}
            for idx, row in enumerate(values[1:], start=2):
                if not row or not row[0]:
                    continue
                mailbox = row[col_map.get("mailbox", 0)].strip() if len(row) > 0 else ""
                phrases = row[col_map.get("key_phrases", 1)].strip() if len(row) > 1 else ""
                tg_chat = strip_float(row[col_map.get("tg_chat", 2)].strip()) if len(row) > 2 else ""
                tags = row[col_map.get("tags_string", 3)].strip() if len(row) > 3 else ""
                print(f"  Row {idx}: mailbox={mailbox!r} phrases={phrases!r} tg_chat={tg_chat!r} tags={tags!r}")
    except gspread.WorksheetNotFound:
        print("  NOT FOUND")

    print()
    print("=" * 80)
    print("MAILBOXES SHEET")
    print("=" * 80)
    try:
        ws = sh.worksheet("mailboxes")
        values = ws.get_all_values()
        if not values:
            print("  EMPTY")
        else:
            headers = [h.strip() for h in values[0]]
            print(f"  Headers: {headers}")
            col_map = {h: i for i, h in enumerate(headers)}
            for idx, row in enumerate(values[1:], start=2):
                if not row or not row[0]:
                    continue
                mailbox = row[col_map.get("mailbox", 0)].strip() if len(row) > 0 else ""
                enabled = row[col_map.get("enabled", 1)].strip() if len(row) > 1 else ""
                subject_phrase = row[col_map.get("subject_phrase", 2)].strip() if len(row) > 2 else ""
                gmail_query = row[col_map.get("gmail_query_base", 3)].strip() if len(row) > 3 else ""
                last_ms = row[col_map.get("last_internal_ms", 4)].strip() if len(row) > 4 else ""
                sent_ids = row[col_map.get("last_sent_ids_json", 5)].strip() if len(row) > 5 else ""
                updated = row[col_map.get("updated_at_utc", 6)].strip() if len(row) > 6 else ""
                notes = row[col_map.get("notes", 7)].strip() if len(row) > 7 else ""
                print(f"  Row {idx}:")
                print(f"    mailbox={mailbox!r}")
                print(f"    enabled={enabled!r}")
                print(f"    subject_phrase={subject_phrase!r}")
                print(f"    gmail_query_base={gmail_query!r}")
                print(f"    last_internal_ms={last_ms!r}")
                print(f"    last_sent_ids_json={sent_ids!r}")
                print(f"    updated_at_utc={updated!r}")
                print(f"    notes={notes!r}")

                # Validate sent_ids JSON
                if sent_ids:
                    try:
                        parsed = json.loads(sent_ids)
                        print(f"    [OK] sent_ids is valid JSON, {len(parsed)} items")
                    except json.JSONDecodeError as e:
                        print(f"    [ERROR] sent_ids is invalid JSON: {e}")
    except gspread.WorksheetNotFound:
        print("  NOT FOUND")

    print()
    print("=" * 80)
    print("CONFIG SHEET")
    print("=" * 80)
    try:
        ws = sh.worksheet("config")
        values = ws.get_all_values()
        if not values:
            print("  EMPTY")
        else:
            for row in values[1:]:
                if not row or not row[0]:
                    continue
                key = row[0].strip()
                val = strip_float(row[1].strip()) if len(row) > 1 else ""
                desc = row[2].strip() if len(row) > 2 else ""
                print(f"  {key} = {val!r}  # {desc}")
    except gspread.WorksheetNotFound:
        print("  NOT FOUND")

    print()
    print("=" * 80)
    print("ANALYSIS")
    print("=" * 80)
    
    # Check for info@unicheck.ai specifically
    print()
    print("Checking info@unicheck.ai:")
    
    # Check setup
    setup_ws = sh.worksheet("setup")
    setup_values = setup_ws.get_all_values()
    setup_headers = [h.strip().lower() for h in setup_values[0]]
    setup_col_map = {h: i for i, h in enumerate(setup_headers)}
    
    found_in_setup = False
    for row in setup_values[1:]:
        if not row or not row[0]:
            continue
        mb = row[setup_col_map.get("mailbox", 0)].strip().lower()
        if mb == "info@unicheck.ai":
            found_in_setup = True
            phrases = row[setup_col_map.get("key_phrases", 1)].strip() if len(row) > 1 else ""
            tg_chat = row[setup_col_map.get("tg_chat", 2)].strip() if len(row) > 2 else ""
            tags = row[setup_col_map.get("tags_string", 3)].strip() if len(row) > 3 else ""
            print(f"  [OK] Found in setup sheet")
            print(f"       key_phrases={phrases!r}")
            print(f"       tg_chat={tg_chat!r}")
            print(f"       tags_string={tags!r}")
            if not phrases:
                print(f"  [WARN] key_phrases is EMPTY — no subject phrase to search for!")
            if not tg_chat:
                print(f"  [WARN] tg_chat is EMPTY — no routing target!")
    
    if not found_in_setup:
        print("  [ERROR] NOT found in setup sheet!")

    # Check mailboxes
    mb_ws = sh.worksheet("mailboxes")
    mb_values = mb_ws.get_all_values()
    mb_headers = [h.strip() for h in mb_values[0]]
    mb_col_map = {h: i for i, h in enumerate(mb_headers)}
    
    found_in_mailboxes = False
    for row in mb_values[1:]:
        if not row or not row[0]:
            continue
        mb = row[mb_col_map.get("mailbox", 0)].strip().lower()
        if mb == "info@unicheck.ai":
            found_in_mailboxes = True
            enabled = row[mb_col_map.get("enabled", 1)].strip() if len(row) > 1 else ""
            subject_phrase = row[mb_col_map.get("subject_phrase", 2)].strip() if len(row) > 2 else ""
            gmail_query = row[mb_col_map.get("gmail_query_base", 3)].strip() if len(row) > 3 else ""
            last_ms = row[mb_col_map.get("last_internal_ms", 4)].strip() if len(row) > 4 else ""
            sent_ids = row[mb_col_map.get("last_sent_ids_json", 5)].strip() if len(row) > 5 else ""
            print(f"  [OK] Found in mailboxes sheet")
            print(f"       enabled={enabled!r}")
            print(f"       subject_phrase={subject_phrase!r}")
            print(f"       gmail_query_base={gmail_query!r}")
            print(f"       last_internal_ms={last_ms!r}")
            print(f"       last_sent_ids_json={sent_ids!r}")
            
            if enabled.lower() != "true":
                print(f"  [WARN] enabled='{enabled}' — should be 'TRUE' to be active!")
            if not subject_phrase:
                print(f"  [WARN] subject_phrase is EMPTY!")
            if not gmail_query:
                print(f"  [WARN] gmail_query_base is EMPTY!")
            if not last_ms or last_ms == "0":
                print(f"  [INFO] last_internal_ms=0 — will bootstrap on first run")
    
    if not found_in_mailboxes:
        print("  [ERROR] NOT found in mailboxes sheet!")

    print()
    print("=" * 80)
    print("ENV CHECK")
    print("=" * 80)
    gmail_mb = os.getenv("GMAIL_IMPERSONATE") or os.getenv("MAILBOX_1_EMAIL", "info@freelance.kz")
    print(f"  GMAIL_IMPERSONATE / MAILBOX_1_EMAIL = {gmail_mb!r}")
    print(f"  This is the ONLY mailbox checker.py currently monitors!")
    print()
    if gmail_mb != "info@unicheck.ai":
        print(f"  [CRITICAL] checker.py is monitoring '{gmail_mb}', NOT 'info@unicheck.ai'!")
        print(f"  To monitor info@unicheck.ai, you would need to:")
        print(f"    1. Change GMAIL_IMPERSONATE in .env to info@unicheck.ai, OR")
        print(f"    2. Run a second instance of checker.py with different .env, OR")
        print(f"    3. Refactor checker.py to monitor ALL mailboxes from the mailboxes sheet")

if __name__ == "__main__":
    main()
