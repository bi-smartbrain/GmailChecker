import json
import os

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build


def main() -> int:
    load_dotenv(r"C:\Rubrain\Secrets\.env")

    sa = os.getenv("GOOGLE_SA_JSON_PATH")
    subj = os.getenv("MAILBOX_1_EMAIL") or os.getenv("GMAIL_IMPERSONATE") or "info@freelance.kz"
    q = os.getenv("Q") or "in:inbox"

    creds = (
        service_account.Credentials.from_service_account_file(
            sa,
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        ).with_subject(subj)
    )
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)

    resp = gmail.users().messages().list(userId="me", labelIds=["INBOX"], q=q, maxResults=10).execute()
    print("q=", json.dumps(q, ensure_ascii=True))
    print("estimate=", resp.get("resultSizeEstimate"))
    print("count=", len(resp.get("messages", []) or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
