# GmailChecker

Сервис мониторинга корпоративных Gmail-ящиков (Google Workspace) с уведомлениями в Telegram.

## Что делает

- Проверяет несколько Gmail-ящиков на наличие писем с определёнными фразами в теме
- Отправляет форматированные уведомления в Telegram (личные чаты, группы)
- Использует Google Sheets как единый источник конфигурации — все настройки меняются на лету без перезапуска
- Масштабируется до ~200 ящиков across multiple Google Workspace тенантов

## Архитектура

```
┌─────────────┐     Gmail API (DWD)     ┌──────────────┐
│  Gmail      │◄────────────────────────┤  checker.py   │
│  Mailboxes  │                         │  (Docker)     │
└─────────────┘                         └──────┬───────┘
                                               │
                        ┌──────────────────────┼──────────────────┐
                        │                      │                  │
                        ▼                      ▼                  ▼
                 ┌─────────────┐        ┌─────────────┐   ┌─────────────┐
                 │ Google      │        │ Google      │   │ Telegram    │
                 │ Sheets      │        │ Sheets      │   │ Bot API     │
                 │ (config)    │        │ (state/log) │   │             │
                 └─────────────┘        └─────────────┘   └─────────────┘
```

### Ключевые решения

- **Gmail API + Domain-Wide Delegation** — IMAP заблокирован Google Workspace, OAuth user-consent не подходит для автоматизации
- **Google Sheets как конфиг** — hot-reload всех настроек без перезапуска
- **Один процесс, все ящики** — каждый цикл читает все enabled-ящики из таблицы, создаёт Gmail API клиент с impersonation
- **Telegram HTML mode** — MarkdownV2 слишком хрупкий для динамического контента

## Структура проекта

```
GmailChecker/
├── checker.py              # Главный сервис (мониторинг, уведомления)
├── format.md               # Шаблон Telegram-уведомления (Markdown → HTML)
├── env_loader.py           # Загрузка секретов (локально vs Docker)
├── docker-compose.yml      # Docker Compose конфигурация
├── Dockerfile              # Образ контейнера
├── requirements.txt        # Python зависимости
├── .dockerignore           # Исключения для Docker build
├── .gitignore              # Исключения для Git
├── scripts/
│   ├── sheets_setup.py     # Инициализация структуры Google Sheets
│   └── verify_mailbox.py   # Проверка данных в таблицах
└── AGENTS.md               # Инструкции для AI-ассистента
```

## Google Sheets структура

Таблица — единый источник конфигурации. Состоит из 4 листов:

### config (глобальные настройки)

| key | value | description |
|---|---|---|
| POLL_INTERVAL_SECONDS | 30 | Интервал между проверками |
| BOOTSTRAP | skip_existing | Пропускать существующие письма при первом запуске |
| TG_ALLOW_NON_PERSONAL | true | Разрешать отправку в группы/каналы |
| TG_CHAT_ID_1 | 302376278 | Личный чат |
| TG_CHAT_ID_5 | 302376278 | Support чат |
| TG_CHAT_ID_6 | -5012137290 | Debug группа |

### mailboxes (ящики для мониторинга)

| mailbox | enabled | subject_phrase | gmail_query_base | tg_chat_id | tags_string | last_internal_ms | last_sent_ids_json | updated_at_utc | notes |
|---|---|---|---|---|---|---|---|---|---|
| info@freelance.kz | TRUE | Новое сообщение... | in:inbox | TG_CHAT_ID_1 | @karyushka ... | 1775015180000 | ["..."] | 2026-04-01... | migrated |

**Поля:**
- `mailbox` — email ящика (Google Workspace user)
- `enabled` — TRUE/FALSE, включает/выключает мониторинг
- `subject_phrase` — фраза для поиска в теме письма
- `gmail_query_base` — базовый Gmail query (обычно `in:inbox`)
- `tg_chat_id` — имя переменной из config (напр. `TG_CHAT_ID_1`) или сырой ID
- `tags_string` — упоминания в Telegram (@username)
- `last_internal_ms` — внутренний timestamp последнего обработанного письма (авто)
- `last_sent_ids_json` — последние 50 ID отправленных писем (авто)
- `updated_at_utc` — время последнего обновления (авто)
- `notes` — заметки

### events (лог событий)

Append-only лог: отправленные сообщения, checkpoint-ы, ошибки.

## Как добавить новый ящик

1. Открой Google Sheets → лист **mailboxes**
2. Добавь строку:
   - `mailbox` — email (напр. `info@unicheck.ai`)
   - `enabled` — `TRUE`
   - `subject_phrase` — фраза для поиска в теме
   - `gmail_query_base` — `in:inbox`
   - `tg_chat_id` — `TG_CHAT_ID_1` (или другой ключ из config)
   - `tags_string` — `@username` (необязательно)
3. Остальные поля заполнятся автоматически
4. **Перезапускать не нужно** — сервис подхватит на следующем цикле

## Как изменить интервал проверки

1. Google Sheets → лист **config**
2. Найди `POLL_INTERVAL_SECONDS`
3. Поменяй значение (напр. `300` для 5 минут)
4. Подхватится на следующем цикле

## Деплой

### Сервер

- Путь: `/opt/GmailChecker`
- Секреты: `/opt/secrets/service_account.json` (Sheets), `/opt/secrets/service_account_freelance.json` (Gmail DWD)
- Env: `/opt/secrets/.env` (TG_TOKEN, CHAT_ID_*)

### Docker

```bash
# Первый запуск
cd /opt/GmailChecker
docker-compose up -d

# Обновление
bash /opt/auto/update_GmailChecker.sh

# Логи
docker logs -f gmail-checker
```

### env_loader.py

Автоматически определяет путь к секретам:
- В Docker: `/secrets/` (смонтировано из `/opt/secrets/`)
- Локально: `../secrets/` (относительно проекта)

Прописывает `GOOGLE_SHEETS_SA_JSON_PATH` и `GOOGLE_SA_JSON_PATH` в окружение.

## Безопасность

- Service Account JSON файлы **не** коммитятся в Git
- `.env` файлы **не** коммитятся
- Docker volume `/opt/secrets` монтируется read-only
- Guardrail: блокировка отправки в группы/каналы если `TG_ALLOW_NON_PERSONAL != true`

## Зависимости

- Python 3.11+
- google-api-python-client, google-auth (Gmail API)
- gspread (Google Sheets)
- requests (Telegram API)
- python-dotenv (загрузка .env)
- colorama (цветной вывод)

## Логирование

Цветной консольный вывод с тегами:
- 🟢 `[mb:...]` — операции с ящиком (зелёный)
- 🔵 `[gmail]` / `[state]` — API вызовы (синий)
- 🟡 `[config]` / `[init]` / `[warn]` — конфиг и предупреждения (жёлтый)
- 🟣 `[mailboxes]` / `[tg]` — список ящиков и Telegram (маджента)
- 🔴 `[error]` — ошибки (красный, жирный)
- ⚪ `[loop]` — границы циклов (циан, dim)
