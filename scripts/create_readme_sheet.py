"""
Add a ReadMe sheet to the Google Sheets config file.
"""
import os
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv(r"C:\Rubrain\Secrets\.env")

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1SS5RanpLrtGHfHgePqWSDRm-57XSRK5TKNecc4FYUfI/edit"
SA_PATH = os.getenv("GOOGLE_SHEETS_SA_JSON_PATH", r"C:\Rubrain\Secrets\service_account.json")

README_CONTENT = [
    ["GmailChecker — Шпаргалка", "", ""],
    ["", "", ""],
    ["Что это", "", ""],
    ["Сервис мониторинга корпоративных Gmail-ящиков. Проверяет письма с определёнными фразами в теме и шлёт уведомления в Telegram.", "", ""],
    ["", "", ""],
    ["Листы таблицы", "", ""],
    ["config", "Глобальные настройки", "POLL_INTERVAL_SECONDS, BOOTSTRAP, TG_CHAT_ID_*, TG_ALLOW_NON_PERSONAL"],
    ["mailboxes", "Ящики для мониторинга", "Каждый ящик: email, фраза, чат, состояние. Добавляй строки — сервис подхватит сам."],
    ["events", "Лог событий", "Append-only: отправленные сообщения, ошибки, checkpoint-и. Не трогай вручную."],
    ["", "", ""],
    ["Как добавить ящик", "", ""],
    ["1. Открой лист mailboxes", "", ""],
    ["2. Заполни строку:", "mailbox", "email ящика (info@unicheck.ai)"],
    ["", "enabled", "TRUE (включён) / FALSE (выключен)"],
    ["", "subject_phrase", "Фраза для поиска в теме письма"],
    ["", "gmail_query_base", "in:inbox (обычно не меняй)"],
    ["", "tg_chat_id", "TG_CHAT_ID_1 или другой ключ из config"],
    ["", "tags_string", "@username для упоминаний (необязательно)"],
    ["3. Остальные поля заполнятся сами. Перезапускать не нужно!", "", ""],
    ["", "", ""],
    ["Как поменять интервал", "", ""],
    ["1. Лист config → POLL_INTERVAL_SECONDS", "", ""],
    ["2. Поменяй значение (напр. 300 = 5 минут)", "", ""],
    ["3. Подхватится на следующем цикле", "", ""],
    ["", "", ""],
    ["Как сменить чат для уведомлений", "", ""],
    ["1. Лист mailboxes → tg_chat_id", "", ""],
    ["2. Поставь TG_CHAT_ID_5 (support) или другой ключ", "", ""],
    ["3. Можно использовать сырой ID (напр. -5012137290)", "", ""],
    ["", "", ""],
    ["Как сбросить состояние ящика", "", ""],
    ["1. Лист mailboxes → last_sent_ids_json", "", ""],
    ["2. Очисти до [] (пустой массив)", "", ""],
    ["3. initialized сбросится автоматически", "", ""],
    ["", "", ""],
    ["Где логи", "", ""],
    ["docker logs -f gmail-checker — цветной вывод в реальном времени", "", ""],
    ["", "", ""],
    ["Где код", "", ""],
    ["GitHub: github.com/bi-smartbrain/GmailChecker", "", ""],
    ["Сервер: /opt/GmailChecker", "", ""],
    ["Секреты: /opt/secrets/", "", ""],
    ["Обновление: bash /opt/auto/update_GmailChecker.sh", "", ""],
]


def main():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(SA_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_url(SPREADSHEET_URL)

    titles = [ws.title for ws in sh.worksheets()]
    if "ReadMe" in titles:
        ws = sh.worksheet("ReadMe")
        sh.del_worksheet(ws)
        print("Deleted old ReadMe sheet")

    new_ws = sh.add_worksheet(title="ReadMe", rows=50, cols=10)
    new_ws.update("A1", README_CONTENT)
    new_ws.freeze(rows=1)

    # Make first row bold and larger
    new_ws.format("A1:C1", {"textFormat": {"bold": True, "fontSize": 14}})

    # Bold section headers
    bold_ranges = ["A3", "A6", "A11", "A20", "A25", "A30", "A35", "A39", "A42"]
    for cell in bold_ranges:
        try:
            new_ws.format(cell, {"textFormat": {"bold": True}})
        except Exception:
            pass

    # Column widths (skip if not supported)
    try:
        new_ws.update_column_width(1, 30)
        new_ws.update_column_width(2, 35)
        new_ws.update_column_width(3, 60)
    except Exception:
        pass

    print("Created ReadMe sheet successfully!")


if __name__ == "__main__":
    main()
