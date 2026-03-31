import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import base64
import html
import re
import shutil

import requests
from dotenv import load_dotenv
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
    # MSK is UTC+3; minute precision.
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


def escape_markdown_v2(text: str) -> str:
    # Escape Telegram MarkdownV2 special characters.
    # https://core.telegram.org/bots/api#markdownv2-style
    return re.sub(r"([_\*\[\]\(\)~`>#+\-=|{}\.!\\])", r"\\\1", text or "")


def render_template(template: str, mapping: dict[str, str]) -> str:
    out = template
    for k, v in mapping.items():
        out = out.replace(k, v)
    return out.strip()


def markdown_bold_to_html(tmpl: str) -> str:
    # Minimal conversion: **bold** -> <b>bold</b>
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


def tg_send(token: str, chat_id: str, text: str, dry_run: bool, *, parse_mode: str | None) -> None:
    if dry_run:
        print("[tg][dry_run]", text)
        return

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
    # Helpful when something goes wrong (e.g., bot not in chat, blocked, etc.).
    if not r.ok:
        raise RuntimeError(f"Telegram send failed: status={r.status_code} body={r.text}")
    r.raise_for_status()
    try:
        payload = r.json()
        mid = payload.get("result", {}).get("message_id")
        print(f"[tg] ok message_id={mid}")
    except Exception:
        print("[tg] ok")


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    data = json.dumps(state, ensure_ascii=True, indent=2)

    # Keep a backup of the last good state.
    try:
        if path.exists():
            bak = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, bak)
    except Exception:
        pass

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    load_env()

    sa_path = os.getenv("GOOGLE_SA_JSON_PATH")
    mailbox = os.getenv("GMAIL_IMPERSONATE") or os.getenv("MAILBOX_1_EMAIL") or "info@freelance.kz"
    if not sa_path or not mailbox:
        print("Missing GOOGLE_SA_JSON_PATH or GMAIL_IMPERSONATE in env")
        return 2
    if not os.path.exists(sa_path):
        print(f"Service account JSON not found: {sa_path}")
        return 2

    tg_token = os.getenv("TG_TOKEN") or os.getenv("TG_BOT_TOKEN")
    # During bring-up, default to personal chat id (CHAT_ID_1).
    tg_chat = (
        os.getenv("TG_CHAT_ID")
        or os.getenv("TG_CHAT")
        or os.getenv("TG_CHANNEL")
        or os.getenv("CHAT_ID_1")
        or os.getenv("CHAT_ID_5")
        or "@RubrainMain"
    )
    tg_dry_run = (os.getenv("TG_DRY_RUN", "true").strip().lower() != "false")

    if tg_chat and not tg_chat.startswith("@"):  # numeric chat ids
        # Some .env files keep inline comments like: CHAT_ID_1=12345 # Name
        tg_chat = tg_chat.split("#", 1)[0].strip()
        tg_chat = tg_chat.split()[0].strip() if tg_chat else tg_chat

    poll_s = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    max_results = int(os.getenv("GMAIL_MAX_RESULTS", "20"))
    # User request: exact phrase match (substring) for the Subject.
    subject_phrase = os.getenv("SUBJECT_PHRASE", "Новое сообщение на Freelance.kz")

    base_query = os.getenv("GMAIL_QUERY", "in:inbox")
    # Narrow the server-side query to reduce calls; still validate exact phrase in code.
    query = f'{base_query} subject:"{subject_phrase}"'
    state_path = Path(os.getenv("STATE_PATH", "state.json"))
    bootstrap = os.getenv("BOOTSTRAP", "skip_existing").strip().lower()  # skip_existing|notify_existing

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

    if not tg_token and not tg_dry_run:
        print("Missing TG token. Set TG_TOKEN (or enable TG_DRY_RUN=true)")
        return 2

    gmail = build_gmail(sa_path, mailbox)

    state = load_state(state_path)
    box_state = state.get(mailbox, {}) if isinstance(state.get(mailbox, {}), dict) else {}
    last_internal_ms = int(box_state.get("last_internal_ms", 0) or 0)
    initialized = bool(box_state.get("initialized", False))
    last_sent_ids = box_state.get("last_sent_ids")
    if not isinstance(last_sent_ids, list):
        last_sent_ids = []
    # Normalize list to strings only.
    last_sent_ids = [str(x) for x in last_sent_ids if x]

    # Backstop for earlier broken state initialization.
    if initialized and last_internal_ms <= 0:
        initialized = False

    print("Checker params:")
    print(f"- mailbox: {mailbox}")
    print(f"- query: {query}")
    print(f"- subject_phrase: {subject_phrase}")
    print(f"- poll_s: {poll_s}")
    print(f"- max_results: {max_results}")
    print(f"- state_path: {state_path}")
    print(f"- last_internal_ms: {last_internal_ms} ({utc_iso_from_ms(last_internal_ms)})")
    print(f"- bootstrap: {bootstrap}")
    print(f"- tg_chat: {tg_chat}")
    print(f"- tg_dry_run: {tg_dry_run}")
    print(f"- template: {template_path}")
    print(f"- tg_parse_mode: {parse_mode}")

    while True:
        try:
            resp = (
                gmail.users()
                .messages()
                .list(userId="me", labelIds=["INBOX"], q=query, maxResults=max_results)
                .execute()
            )
            msgs = resp.get("messages", []) or []

            # Fetch metadata and only emit messages newer than our last checkpoint.
            newest_seen = last_internal_ms
            to_notify: list[dict[str, Any]] = []

            # Collect candidates first; if this is the first run and bootstrap=skip_existing,
            # we will checkpoint to the newest candidate without sending.
            candidates: list[dict[str, Any]] = []

            for m in msgs:
                mid = m.get("id")
                if not mid:
                    continue
                msg = (
                    gmail.users()
                    .messages()
                    .get(
                        userId="me",
                        id=mid,
                        format="full",
                    )
                    .execute()
                )

                internal_ms_raw = msg.get("internalDate")
                internal_ms = int(internal_ms_raw) if internal_ms_raw else 0
                newest_seen = max(newest_seen, internal_ms)

                headers = get_headers(msg)
                subj = headers.get("subject", "")
                if subject_phrase not in subj:
                    continue

                candidates.append(msg)

            if not initialized:
                if bootstrap == "skip_existing":
                    # On first run, don't notify historical mail; just checkpoint.
                    cp = 0
                    for msg in candidates:
                        ms_raw = msg.get("internalDate")
                        ms = int(ms_raw) if ms_raw else 0
                        cp = max(cp, ms)
                    if cp <= 0:
                        cp = int(time.time() * 1000)

                    initialized = True
                    last_internal_ms = cp
                    state[mailbox] = {
                        "initialized": True,
                        "last_internal_ms": last_internal_ms,
                        "last_internal_utc": utc_iso_from_ms(last_internal_ms),
                        "last_sent_ids": last_sent_ids[-50:],
                    }
                    save_state(state_path, state)
                    print(f"[init] checkpoint set to {utc_iso_from_ms(last_internal_ms)}")
                    time.sleep(poll_s)
                    continue

                # notify_existing: proceed and notify everything that matches.
                initialized = True

            for msg in candidates:
                mid = str(msg.get("id") or "")
                if not mid or mid in last_sent_ids:
                    continue

                internal_ms_raw = msg.get("internalDate")
                internal_ms = int(internal_ms_raw) if internal_ms_raw else 0
                if internal_ms <= last_internal_ms:
                    continue

                to_notify.append(msg)

            if True:
                # Notify oldest-to-newest for readability.
                to_notify.sort(key=lambda x: int(x.get("internalDate") or 0))
                sent_any = False
                for msg in to_notify:
                    headers = get_headers(msg)
                    subj = safe(headers.get("subject", ""))
                    from_ = safe(headers.get("from", ""))
                    internal_ms_raw = msg.get("internalDate")
                    internal_ms = int(internal_ms_raw) if internal_ms_raw else 0

                    date_msk = fmt_msk_from_ms(internal_ms) if internal_ms else ""
                    preview_raw = extract_text_preview_200(msg)

                    # We'll send with Telegram HTML parse_mode.
                    preview = html.escape(preview_raw)
                    from_html = html.escape(from_)
                    subj_html = html.escape(subj)
                    mailbox_html = html.escape(mailbox)
                    date_html = html.escape(date_msk)

                    tmpl_md = get_template()
                    tmpl_html = markdown_bold_to_html(tmpl_md)

                    text = render_template(
                        tmpl_html,
                        {
                            "<email>": mailbox_html,
                            "<from>": from_html,
                            "<subject>": subj_html,
                            "<dd.mm.yyyy HH:MM>": date_html,
                            "<first 150 characters of the email body>": preview[:150],
                            "<first 200 characters of the email body>": preview[:200],
                        },
                    )

                    tg_send(tg_token or "", tg_chat, text, tg_dry_run, parse_mode=parse_mode)
                    last_internal_ms = max(last_internal_ms, internal_ms)
                    last_sent_ids.append(str(msg.get("id") or ""))
                    last_sent_ids = [x for x in last_sent_ids if x][-50:]
                    sent_any = True

                if sent_any:
                    state[mailbox] = {
                        "initialized": True,
                        "last_internal_ms": last_internal_ms,
                        "last_internal_utc": utc_iso_from_ms(last_internal_ms),
                        "last_sent_ids": last_sent_ids[-50:],
                    }
                    save_state(state_path, state)

        except Exception as e:
            print(f"[error] {type(e).__name__}: {e}")

        time.sleep(poll_s)


if __name__ == "__main__":
    raise SystemExit(main())
