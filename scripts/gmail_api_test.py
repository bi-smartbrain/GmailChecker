import json
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build


def _decode_b64url(data: str) -> bytes:
    # We don't actually need payload decode for this smoke test,
    # but keeping helper around if needed later.
    import base64

    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _env_first(*keys: str) -> tuple[str, str] | tuple[None, None]:
    for k in keys:
        v = os.getenv(k)
        if v:
            return k, v
    return None, None


def main() -> int:
    default_dotenv = r"C:\Rubrain\Secrets\.env"
    dotenv_path = os.getenv("DOTENV_PATH", default_dotenv)
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)

    # Service account JSON (currently you already have it for Sheets).
    sa_path = os.getenv("GOOGLE_SA_JSON_PATH", r"C:\Rubrain\Secrets\service_account.json")
    if not os.path.exists(sa_path):
        print(f"Service account JSON not found: {sa_path}")
        return 2

    # User to impersonate (must be in the Workspace domain, and DWD must be configured).
    _, subject = _env_first("GMAIL_IMPERSONATE", "MAILBOX_1_EMAIL", "GMAIL_USER")
    if not subject:
        print("Missing impersonation target.")
        print("Set GMAIL_IMPERSONATE=info@freelance.kz (or provide MAILBOX_1_EMAIL)")
        return 2

    limit = int(os.getenv("GMAIL_LIMIT", "10"))

    scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
    ]

    # Read only non-secret identifiers from the JSON for operator guidance.
    try:
        with open(sa_path, "r", encoding="utf-8") as f:
            sa_info = json.load(f)
    except Exception as e:
        print(f"Failed to read service account JSON: {type(e).__name__}: {e}")
        return 2

    sa_client_email = sa_info.get("client_email")
    sa_client_id = sa_info.get("client_id")
    project_id = sa_info.get("project_id")

    print("Gmail API smoke test (Service Account + Domain-Wide Delegation)")
    print(f"- dotenv: {dotenv_path} (exists={os.path.exists(dotenv_path)})")
    print(f"- sa_json: {sa_path}")
    print(f"- project_id: {project_id}")
    print(f"- service_account: {sa_client_email}")
    print(f"- service_account_client_id: {sa_client_id}")
    print(f"- impersonate_user: {subject}")
    print(f"- scope: {scopes[0]}")
    print(f"- limit: {limit}")

    try:
        creds = service_account.Credentials.from_service_account_file(sa_path, scopes=scopes)
        creds = creds.with_subject(subject)
    except Exception as e:
        print(f"Failed to build delegated credentials: {type(e).__name__}: {e}")
        return 3

    try:
        # cache_discovery=False avoids writing cache files.
        gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"Failed to build Gmail API client: {type(e).__name__}: {e}")
        return 3

    try:
        profile = gmail.users().getProfile(userId="me").execute()
        print(f"Profile OK: email={profile.get('emailAddress')} messagesTotal={profile.get('messagesTotal')}")
    except Exception as e:
        print(f"Profile FAILED: {type(e).__name__}: {e}")
        print("If this is 401/403, check:")
        print("- In Google Cloud project: Gmail API is enabled")
        print("- Service account has Domain-Wide Delegation enabled")
        print("- Admin console -> Security -> API controls -> Domain-wide delegation:")
        print("  add this service account client_id with the required scopes")
        return 4

    try:
        resp = (
            gmail.users()
            .messages()
            .list(userId="me", labelIds=["INBOX"], maxResults=limit)
            .execute()
        )
        msgs = resp.get("messages", [])
        print(f"INBOX list OK: returned={len(msgs)}")
    except Exception as e:
        print(f"INBOX list FAILED: {type(e).__name__}: {e}")
        return 5

    for m in msgs:
        mid = m.get("id")
        if not mid:
            continue
        try:
            msg = (
                gmail.users()
                .messages()
                .get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["Date", "From", "Subject", "Message-Id"],
                )
                .execute()
            )
        except Exception as e:
            print(f"- message {mid}: FAILED to fetch ({type(e).__name__}: {e})")
            continue

        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", []) if "name" in h and "value" in h}
        date = headers.get("date", "")
        from_ = headers.get("from", "")
        subj = headers.get("subject", "")
        msgid = headers.get("message-id", "")
        internal_ms = msg.get("internalDate")
        internal_ts = ""
        if internal_ms:
            try:
                internal_ts = datetime.fromtimestamp(int(internal_ms) / 1000, tz=timezone.utc).isoformat()
            except Exception:
                internal_ts = str(internal_ms)

        print(f"- id {mid}")
        print(f"  internalDate(utc): {internal_ts}")
        print(f"  Date: {date}")
        print(f"  From: {from_}")
        print(f"  Subject: {subj}")
        print(f"  Message-Id: {msgid}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
