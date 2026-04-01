import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import base64
import html
import re
import sys

import requests
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials as SheetsCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build


def load_env() -> None:
    default_dotenv = r"C:\Rubrain\Secrets\.env"
    dotenv_path = os.getenv("DOTENV_PATH", default_dotenv)
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)


def utc_iso_from_ms(ms: str | int | None) -> str:
    if ms is None:
        return ""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return str(ms)


def safe(s: str) -> str:
    return (s or "").replace("\r", " ").replace("\n", " ").strip()


def fmt_msk_from_ms(ms: int) -> str:
    dt_utc = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    dt_msk = dt_utc + timedelta(hours=3)
    return dt_msk.strftime("%d.%m.%Y %H:%M")


def decode_b64url(data: str) -> str:
    pad = "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(data + pad)
    return raw.decode("utf-8", errors="replace")


def strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def iter_payload_parts(payload: dict[str, Any]):
    yield payload
    for p in payload.get("parts", []) or []:
        if isinstance(p, dict):
            yield from iter_payload_parts(p)


def extract_text_preview_200(msg: dict[str, Any]) -> str:
    payload = msg.get("payload") or {}

    plain_candidates: list[str] = []
    html_candidates: list[str] = []

    for part in iter_payload_parts(payload if isinstance(payload, dict) else {}):
        mime = (part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        data = body.get("data")
        if not data or not isinstance(data, str):
            continue
        if mime == "text/plain":
            plain_candidates.append(decode_b64url(data))
        elif mime == "text/html":
            html_candidates.append(decode_b64url(data))

    text = ""
    for t in plain_candidates:
        t = safe(t)
        if t:
            text = t
            break

    if not text and html_candidates:
        text = strip_html(html_candidates[0])

    if not text:
        text = safe(msg.get("snippet", ""))

    return text[:200]


def render_template(template: str, mapping: dict[str, str]) -> str:
    out = template
    for k, v in mapping.items():
        out = out.replace(k, v)
    return out.strip()


def markdown_bold_to_html(tmpl: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", tmpl, flags=re.DOTALL)


def build_gmail(sa_path: str, subject_user: str):
    scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    creds = service_account.Credentials.from_service_account_file(sa_path, scopes=scopes)
    creds = creds.with_subject(subject_user)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_headers(msg: dict[str, Any]) -> dict[str, str]:
    headers_list = msg.get("payload", {}).get("headers", []) or []
    out: dict[str, str] = {}
    for h in headers_list:
        name = h.get("name")
        value = h.get("value")
        if name and value:
            out[name.lower()] = value
    return out


def tg_send(token: str, chat_id: str, text: str, dry_run: bool, *, parse_mode: str | None) -> str | None:
    if dry_run:
        first_line = (text.splitlines() or [""])[0]
        enc = sys.stdout.encoding or "utf-8"
        safe_first = first_line.encode(enc, errors="backslashreplace").decode(enc, errors="ignore")
        print(f"[tg][dry_run] to={chat_id} bytes={len(text.encode('utf-8'))} first_line={safe_first}")
        return None

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    print(f"[tg] sending to {chat_id} bytes={len(text.encode('utf-8'))}")
    r = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            **({"parse_mode": parse_mode} if parse_mode else {}),
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    if not r.ok:
        raise RuntimeError(f"Telegram send failed: status={r.status_code} body={r.text}")
    r.raise_for_status()
    try:
        payload = r.json()
        mid = payload.get("result", {}).get("message_id")
        print(f"[tg] ok message_id={mid}")
        return str(mid) if mid is not None else None
    except Exception:
        print("[tg] ok")
        return None


def sheets_client(sa_path: str) -> gspread.Client:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = SheetsCredentials.from_service_account_file(sa_path, scopes=scopes)
    return gspread.authorize(creds)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_bool(s: str) -> bool:
    return (s or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_int(s: str, default: int = 0) -> int:
    try:
        return int(str(s).strip())
    except Exception:
        return default


def safe_json_list(s: str) -> list[str]:
    try:
        v = json.loads(s) if s else []
        if isinstance(v, list):
            return [str(x) for x in v if x]
    except Exception:
        pass
    return []


def strip_dotzero(val: str) -> str:
    if val.endswith(".0"):
        return val[:-2]
    return val


def load_key_value_sheet(ws) -> dict[str, str]:
    values = ws.get_all_values()
    if not values:
        return {}
    out: dict[str, str] = {}
    for row in values[1:]:
        if not row or not row[0]:
            continue
        key = row[0].strip()
        if key.startswith("#"):
            continue
        val = row[1].strip() if len(row) > 1 else ""
        val = strip_dotzero(val)
        if key and val:
            out[key] = val
    return out


def read_mailboxes_sheet(ws) -> tuple[list[dict[str, Any]], dict[str, int]]:
    values = ws.get_all_values()
    if not values:
        raise RuntimeError("mailboxes sheet has no header row")

    headers = [h.strip() for h in values[0]]
    col = {h: i + 1 for i, h in enumerate(headers) if h.strip()}
    required = ["mailbox", "enabled", "subject_phrase", "gmail_query_base", "tg_chat_id", "tags_string", "last_internal_ms", "last_sent_ids_json", "updated_at_utc", "notes"]
    for r in required:
        if r not in col:
            raise RuntimeError(f"mailboxes sheet missing required column: {r}")

    mailboxes: list[dict[str, Any]] = []
    for idx, row in enumerate(values[1:], start=2):
        if not row or not row[0]:
            continue
        mb_email = row[col["mailbox"] - 1].strip()
        if not mb_email:
            continue

        def cell_val(key: str) -> str:
            c = col.get(key)
            if c is None:
                return ""
            v = row[c - 1] if len(row) >= c else ""
            return strip_dotzero(str(v).strip())

        last_sent = safe_json_list(cell_val("last_sent_ids_json"))
        last_ms = parse_int(cell_val("last_internal_ms"), 0)

        mailboxes.append({
            "row": idx,
            "mailbox": mb_email,
            "enabled": parse_bool(cell_val("enabled")),
            "subject_phrase": cell_val("subject_phrase"),
            "gmail_query_base": cell_val("gmail_query_base") or "in:inbox",
            "tg_chat_id": cell_val("tg_chat_id"),
            "tags_string": cell_val("tags_string"),
            "last_internal_ms": last_ms,
            "last_sent_ids": last_sent,
            "initialized": last_ms > 0,
            "updated_at_utc": cell_val("updated_at_utc"),
            "notes": cell_val("notes"),
        })

    return mailboxes, col


def ws_update_cell(ws, row: int, col_idx: int, value: str) -> None:
    ws.update_cell(row, col_idx, value)


def ensure_mailbox_exists(ws, col: dict[str, int], mailbox: str, *, subject_phrase: str, gmail_query_base: str, tg_chat_id: str = "", tags_string: str = "") -> None:
    values = ws.get_all_values()
    if not values:
        raise RuntimeError("mailboxes sheet has no header row")

    target = mailbox.strip().lower()
    for idx, row in enumerate(values[1:], start=2):
        if row and row[0].strip().lower() == target:
            return

    ws.append_row(
        [
            mailbox,
            "TRUE",
            subject_phrase,
            gmail_query_base,
            tg_chat_id,
            tags_string,
            "0",
            "[]",
            now_utc_iso(),
            "auto-added by checker.py",
        ],
        value_input_option="RAW",
    )


def main() -> int:
    load_env()

    spreadsheet_url = "https://docs.google.com/spreadsheets/d/1SS5RanpLrtGHfHgePqWSDRm-57XSRK5TKNecc4FYUfI/edit"
    sheets_sa_path = os.getenv("GOOGLE_SHEETS_SA_JSON_PATH", r"C:\Rubrain\Secrets\service_account.json")
    sa_path = os.getenv("GOOGLE_SA_JSON_PATH")

    if not os.path.exists(sheets_sa_path):
        print(f"Sheets service account JSON not found: {sheets_sa_path}")
        return 2
    if not sa_path or not os.path.exists(sa_path):
        print(f"Gmail service account JSON not found: {sa_path}")
        return 2

    tg_token = os.getenv("TG_TOKEN") or os.getenv("TG_BOT_TOKEN")
    tg_dry_run = (os.getenv("TG_DRY_RUN", "false").strip().lower() != "false")

    if not tg_token and not tg_dry_run:
        print("Missing TG token. Set TG_TOKEN (or enable TG_DRY_RUN=true)")
        return 2

    gc = sheets_client(sheets_sa_path)
    sh = gc.open_by_url(spreadsheet_url)

    # Load global config from "config" sheet.
    try:
        config_ws = sh.worksheet("config")
        cfg = load_key_value_sheet(config_ws)
        for k, v in cfg.items():
            os.environ[k] = v
            print(f"[config] applied {k}={v}")
    except gspread.WorksheetNotFound:
        print("[warn] 'config' sheet not found; using .env defaults")
        cfg = {}

    # Guardrail: block group/channel sends unless explicitly allowed.
    allow_non_personal = os.getenv("TG_ALLOW_NON_PERSONAL", "false").strip().lower()

    poll_s = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    max_results = int(os.getenv("GMAIL_MAX_RESULTS", "20"))
    bootstrap = os.getenv("BOOTSTRAP", "skip_existing").strip().lower()

    template_path = Path(os.getenv("FORMAT_PATH", "format.md"))
    if not template_path.exists():
        print(f"Missing template file: {template_path}")
        return 2
    template_mtime = 0.0
    template = ""

    def get_template() -> str:
        nonlocal template, template_mtime
        try:
            mtime = template_path.stat().st_mtime
        except OSError:
            return template
        if not template or mtime != template_mtime:
            template = template_path.read_text(encoding="utf-8", errors="replace")
            template_mtime = mtime
        return template

    parse_mode = os.getenv("TG_PARSE_MODE", "HTML")

    mailboxes_ws = sh.worksheet("mailboxes")
    events_ws = sh.worksheet("events")

    # Cache for Gmail clients: mailbox -> client
    gmail_clients: dict[str, Any] = {}

    print(f"[init] checker started, poll_interval={poll_s}s, bootstrap={bootstrap}, dry_run={tg_dry_run}")
    print(f"[init] template={template_path}, parse_mode={parse_mode}")

    loop_counter = 0
    while True:
        loop_counter += 1
        print(f"\n{'='*60}")
        print(f"[loop #{loop_counter}] starting at {datetime.now(timezone.utc).isoformat()}")

        try:
            # 1) Refresh global config.
            try:
                new_cfg = load_key_value_sheet(sh.worksheet("config"))
                for k, v in new_cfg.items():
                    os.environ[k] = v
                print(f"[config] refreshed {len(new_cfg)} keys")
            except gspread.WorksheetNotFound:
                pass

            # 2) Read ALL mailboxes from the unified mailboxes sheet.
            mailboxes, col_map = read_mailboxes_sheet(mailboxes_ws)
            enabled_mbs = [mb for mb in mailboxes if mb["enabled"]]
            print(f"[mailboxes] total={len(mailboxes)} enabled={len(enabled_mbs)} {[mb['mailbox'] for mb in enabled_mbs]}")

            for mb in mailboxes:
                email = mb["mailbox"]
                row = mb["row"]

                if not mb["enabled"]:
                    print(f"[mb:{email}] DISABLED, skipping")
                    continue

                print(f"[mb:{email}] enabled=True phrase={mb['subject_phrase']!r} query_base={mb['gmail_query_base']!r}")
                print(f"[mb:{email}] tg_chat_id={mb['tg_chat_id']!r} tags={mb['tags_string']!r}")
                print(f"[mb:{email}] last_internal_ms={mb['last_internal_ms']} initialized={mb['initialized']} sent_ids={len(mb['last_sent_ids'])}")

                # If sent_ids were cleared, reset initialization.
                if not mb["last_sent_ids"]:
                    print(f"[mb:{email}] sent_ids cleared, resetting initialization")
                    mb["initialized"] = False
                    mb["last_internal_ms"] = 0

                # Build or reuse Gmail client.
                if email not in gmail_clients:
                    print(f"[mb:{email}] creating new Gmail API client")
                    gmail_clients[email] = build_gmail(sa_path, email)
                gmail = gmail_clients[email]

                # Resolve chat ID.
                tg_chat = mb["tg_chat_id"]
                if not tg_chat:
                    # Fallback: try config keys.
                    for fallback in ["TG_CHAT_ID_1", "CHAT_ID_1"]:
                        raw = os.getenv(fallback)
                        if raw:
                            tg_chat = strip_dotzero(str(raw).strip())
                            break
                if not tg_chat:
                    print(f"[mb:{email}] SKIP: no tg_chat_id configured")
                    continue

                # Guardrail check per-mailbox.
                if not allow_non_personal and tg_chat.startswith("-"):
                    print(f"[mb:{email}] BLOCKED: tg_chat={tg_chat} is a group/channel and TG_ALLOW_NON_PERSONAL is not true")
                    continue

                subject_phrase = mb["subject_phrase"]
                base_query = mb["gmail_query_base"]
                query = f'{base_query} subject:"{subject_phrase}"'
                print(f"[mb:{email}] query={query!r}")

                # 3) Query Gmail API.
                resp = gmail.users().messages().list(userId="me", labelIds=["INBOX"], q=query, maxResults=max_results).execute()
                msgs = resp.get("messages", []) or []
                print(f"[mb:{email}] API returned {len(msgs)} message IDs")

                candidates: list[dict[str, Any]] = []
                for m in msgs:
                    mid = m.get("id")
                    if not mid:
                        continue
                    msg = gmail.users().messages().get(userId="me", id=mid, format="full").execute()
                    internal_ms = int(msg.get("internalDate") or 0)
                    headers = get_headers(msg)
                    subj = headers.get("subject", "")
                    if subject_phrase not in subj:
                        print(f"[mb:{email}] SKIP msg {mid[:12]}... subject mismatch: {subj!r}")
                        continue
                    print(f"[mb:{email}] CANDIDATE msg {mid[:12]}... subj={subj!r} ts={internal_ms}")
                    msg["_internal_ms"] = internal_ms
                    candidates.append(msg)

                print(f"[mb:{email}] {len(candidates)} candidates after subject filter")

                # 4) Bootstrap if not initialized.
                if not mb["initialized"]:
                    print(f"[mb:{email}] not initialized, bootstrap={bootstrap}")
                    if bootstrap == "skip_existing":
                        cp = 0
                        for msg in candidates:
                            cp = max(cp, msg["_internal_ms"])
                        if cp <= 0:
                            cp = int(time.time() * 1000)

                        mb["initialized"] = True
                        mb["last_internal_ms"] = cp
                        ws_update_cell(mailboxes_ws, row, col_map["last_internal_ms"], str(cp))
                        ws_update_cell(mailboxes_ws, row, col_map["last_sent_ids_json"], "[]")
                        ws_update_cell(mailboxes_ws, row, col_map["updated_at_utc"], now_utc_iso())
                        ws_update_cell(mailboxes_ws, row, col_map["notes"], "checkpoint initialized")

                        events_ws.append_row(
                            [now_utc_iso(), "INFO", "GmailChecker", email, "init_checkpoint", "", str(cp), "", subject_phrase, "", tg_chat, "", ""],
                            value_input_option="RAW",
                        )
                        print(f"[mb:{email}] checkpoint set to {utc_iso_from_ms(cp)}")
                        continue
                    mb["initialized"] = True
                    print(f"[mb:{email}] bootstrap={bootstrap}, marking initialized without checkpoint")

                # 5) Filter against known IDs and timestamp.
                to_notify: list[dict[str, Any]] = []
                for msg in candidates:
                    mid = str(msg.get("id") or "")
                    if mid in mb["last_sent_ids"]:
                        print(f"[mb:{email}] SKIP msg {mid[:12]}... already sent")
                        continue
                    internal_ms = msg["_internal_ms"]
                    if internal_ms < mb["last_internal_ms"]:
                        print(f"[mb:{email}] SKIP msg {mid[:12]}... ts={internal_ms} < checkpoint={mb['last_internal_ms']}")
                        continue
                    print(f"[mb:{email}] TO NOTIFY msg {mid[:12]}... ts={internal_ms}")
                    to_notify.append(msg)

                print(f"[mb:{email}] {len(to_notify)} messages to notify")

                # 6) Send notifications.
                to_notify.sort(key=lambda x: x["_internal_ms"])
                sent_any = False
                for msg in to_notify:
                    headers = get_headers(msg)
                    subj = safe(headers.get("subject", ""))
                    from_ = safe(headers.get("from", ""))
                    internal_ms = msg["_internal_ms"]

                    date_msk = fmt_msk_from_ms(internal_ms) if internal_ms else ""
                    preview_raw = extract_text_preview_200(msg)
                    preview = html.escape(preview_raw)
                    from_html = html.escape(from_)
                    subj_html = html.escape(subj)
                    mailbox_html = html.escape(email)
                    date_html = html.escape(date_msk)

                    tmpl_html = markdown_bold_to_html(get_template())

                    tags = mb["tags_string"] or os.getenv("DEFAULT_TAGS", "")

                    print(f"[mb:{email}] SEND msg {msg.get('id','')[:12]}... from={from_!r} subj={subj!r} -> tg_chat={tg_chat}")

                    text = render_template(
                        tmpl_html,
                        {
                            "<email>": mailbox_html,
                            "<from>": from_html,
                            "<subject>": subj_html,
                            "<dd.mm.yyyy HH:MM>": date_html,
                            "<first 150 characters of the email body>": preview[:150],
                            "<first 200 characters of the email body>": preview[:200],
                            "<tags>": tags,
                        },
                    )

                    tg_mid = tg_send(tg_token or "", tg_chat, text, tg_dry_run, parse_mode=parse_mode)
                    mb["last_internal_ms"] = max(mb["last_internal_ms"], internal_ms)
                    mb["last_sent_ids"].append(str(msg.get("id") or ""))
                    mb["last_sent_ids"] = [x for x in mb["last_sent_ids"] if x][-50:]
                    sent_any = True

                    events_ws.append_row(
                        [now_utc_iso(), "INFO", "GmailChecker", email, "sent", str(msg.get("id") or ""), str(internal_ms), from_, subj, preview_raw[:200], tg_chat, tg_mid or "", ""],
                        value_input_option="RAW",
                    )

                if sent_any:
                    print(f"[mb:{email}] updating state: last_ms={mb['last_internal_ms']} sent_ids={len(mb['last_sent_ids'])}")
                    ws_update_cell(mailboxes_ws, row, col_map["last_internal_ms"], str(mb["last_internal_ms"]))
                    ws_update_cell(mailboxes_ws, row, col_map["last_sent_ids_json"], json.dumps(mb["last_sent_ids"][-50:], ensure_ascii=True))
                    ws_update_cell(mailboxes_ws, row, col_map["updated_at_utc"], now_utc_iso())
                else:
                    print(f"[mb:{email}] no new messages")

        except Exception as e:
            print(f"[error] {type(e).__name__}: {e}")
            try:
                events_ws.append_row(
                    [now_utc_iso(), "ERROR", "GmailChecker", "", "error", "", "", "", "", "", "", "", f"{type(e).__name__}: {e}"],
                    value_input_option="RAW",
                )
            except Exception:
                pass

        print(f"[loop #{loop_counter}] cycle complete, sleeping {poll_s}s")
        time.sleep(poll_s)


if __name__ == "__main__":
    raise SystemExit(main())
