# AGENTS.md — Инструкции для AI-ассистента

## О проекте

GmailChecker — сервис мониторинга Gmail-ящиков Google Workspace с Telegram-уведомлениями.
Google Sheets — единый источник конфигурации (hot-reload без перезапуска).

## Сервер

- SSH: `root@bi.smartbrain.io`
- Проекты: `/opt/<ProjectName>/`
- Секреты: `/opt/secrets/` (`.env`, `service_account.json`, `service_account_freelance.json`)
- Авто-обновление: `/opt/auto/update_<ProjectName>.sh`
- Docker Compose в каждом проекте

## Архитектура сервиса

### checker.py
- Один процесс мониторит ВСЕ enabled-ящики из листа `mailboxes`
- Gmail API client cache: один клиент на ящик, переиспользуется между циклами
- Domain-Wide Delegation через `service_account_freelance.json` (impersonation каждого пользователя)
- Hot-reload: `config`, `mailboxes` читаются КАЖДЫЙ цикл
- Операционные переменные (`poll_s`, `max_results`, `bootstrap`, `tg_dry_run`, `allow_non_personal`) перечитываются из `os.environ` после каждого обновления config sheet

### env_loader.py
- Определяет путь к секретам: `/secrets/` (Docker) или `../secrets/` (локально)
- Загружает `.env` из secrets-директории
- Прописывает `GOOGLE_SHEETS_SA_JSON_PATH` и `GOOGLE_SA_JSON_PATH` в os.environ

### Google Sheets структура
- `config` — key/value глобальные настройки
- `mailboxes` — unified sheet: конфиг + routing + state для каждого ящика
- `events` — append-only лог (sent, checkpoint, error)

### tg_chat_id в mailboxes
- Если значение начинается с `TG_CHAT_ID` или `CHAT_ID` → резолвится из config/env
- Иначе → используется как сырой ID
- Fallback: `TG_CHAT_ID_1` из .env

### Telegram guardrails
- Если `tg_chat` начинается с `-` (группа/канал) и `TG_ALLOW_NON_PERSONAL != true` → блокировка
- Parse mode: HTML (не MarkdownV2)
- `**bold**` → `<b>bold</b>` через regex

### Цветной лог
- colorama для Windows-совместимости
- Теги: loop(cyan), config(yellow), mailboxes(magenta), mb(green), gmail(blue), notify(cyan), send(green+bold), tg(magenta), state(blue), error(red+bold), warn(yellow)

## Деплой паттерн

### Dockerfile
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "checker.py"]
```

### docker-compose.yml
```yaml
services:
  <service-name>:
    build: .
    image: <service-name>:latest
    container_name: <service-name>
    restart: unless-stopped
    working_dir: /app
    environment:
      - PYTHONUNBUFFERED=1
      - TZ=Europe/Moscow
    volumes:
      - /opt/secrets:/secrets:ro
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
        compress: "true"
```

### update скрипт (/opt/auto/update_<Project>.sh)
```bash
set -e
cd /opt/<Project>
docker-compose down
git reset --hard HEAD
git pull origin master
docker-compose build
docker-compose up -d
# Safe cleanup: remove unused images, keep builds for 168h
docker image prune -f
docker builder prune -f --filter "until=168h"
# Self-update: copy to /opt/auto/ for future runs
cp "$(dirname "$0")/update_<Project>.sh" /opt/auto/update_<Project>.sh 2>/dev/null || true
```

### Локальные скрипты
- `scripts/update_GmailChecker.sh` — локальная копия авто-скрипта (обновляется при push)
- `scripts/update_GmailChecker.auto.sh` — копия с прод сервера, добавлена в `.gitignore`

## Частые задачи

### Добавить ящик
Добавить строку в лист `mailboxes` с `enabled=TRUE`. Перезапуск не нужен.

### Изменить интервал
Поменять `POLL_INTERVAL_SECONDS` в листе `config`. Подхватится на следующем цикле.

### Сбросить состояние ящика
Очистить `last_sent_ids_json` до `[]` в листе `mailboxes`. `initialized` сбросится автоматически.

### Отладка
- `docker logs -f gmail-checker` — цветной лог в реальном времени
- `scripts/verify_mailbox.py` — валидация данных в Sheets
- `TG_DRY_RUN=true` в config — режим без отправки в Telegram

## Важные нюансы

1. **Не кешировать** `setup`/`mailboxes`/`config` вне цикла — hot-reload сломается
2. **Sheets float conversion**: отрицательные числа становятся `-5012137290.0` — всегда `strip_dotzero()`
3. **Bootstrap**: `skip_existing` создаёт checkpoint из самого нового письма, `notify_existing` шлёт всё
4. **IMAP заблокирован** Google Workspace — только Gmail API + DWD
5. **Gmail API не помечает письма как прочитанные** — это намеренное поведение
6. **last_sent_ids_json** хранит последние 50 ID — защита от дубликатов
7. **Навыки (skills)** для AI-ассистента: отдельный репозиторий `git@github.com:bi-smartbrain/smartbrain-rules.git`
   - Содержит: `about-me`, `server-deploy`, `gmail-dwd`, `sheets-config`, `telegram-bot`, `colored-logging`
   - Клонировать в `C:\Users\<user>\.config\opencode\skills\` для обнаружения OpenCode

## Ключевые функции

- `strip_dotzero()` — utils.py, очистка `.0` из float значений Google Sheets
- `load_gmail_client()` — создание/кэширование Gmail API клиента с DWD
- `extract_text_preview()` — извлечение текстового превью из письма (до 300 символов)
- `send_telegram()` — отправка уведомления с HTML formatting и guardrails
