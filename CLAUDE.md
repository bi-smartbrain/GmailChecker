# CLAUDE.md

Контекст для Claude Code в этом репозитории. Общая инструкция для AI-ассистентов (сервер, деплой, частые задачи) также живёт в [AGENTS.md](AGENTS.md) — этот файл её не дублирует, а дополняет тем, что специфично для работы с кодом.

## О проекте

GmailChecker — монолитный сервис мониторинга Gmail-ящиков Google Workspace с уведомлениями в Telegram. Google Sheets — единственный источник конфигурации и состояния (hot-reload без перезапуска). Весь сервис — один файл [checker.py](checker.py) (~650 строк), без пакетов и модулей — только `checker.py` + тонкий `env_loader.py`.

## Команды

```bash
pip install -r requirements.txt
python checker.py                    # локальный запуск (нужны секреты в ../secrets/)

docker compose up -d --build         # запуск в контейнере (сервер на Compose v2 — плагин, не отдельный docker-compose)
docker logs -f gmail-checker         # цветной лог в реальном времени

python scripts/verify_mailbox.py     # валидация данных в Google Sheets
python scripts/sheets_setup.py       # (пере)инициализация структуры Sheets
```

Тестов и линтера в проекте нет.

## Архитектура

- **checker.py** — весь сервис в одном файле: bootstrapping окружения, Gmail API клиент (DWD), чтение/запись Google Sheets, рендер шаблона, отправка в Telegram, главный `while True` цикл в `main()`.
- **env_loader.py** — определяет путь к секретам (`/secrets/` в Docker, `../secrets/` локально) и грузит `.env`; `import env_loader` вызывается ради побочного эффекта (`load_env()` в checker.py:64).
- **format.md** — шаблон Telegram-уведомления (Markdown-подобный → HTML). Перечитывается по `mtime` каждый цикл (`get_template()` в checker.py:403) — правки в файле подхватываются без перезапуска.
- **scripts/** — вспомогательные одноразовые скрипты (инспекция/настройка Sheets, тесты Gmail API), не часть рантайма.
- **state.json** — легаси-файл от старой архитектуры, **не используется** нигде в checker.py (в `.gitignore`). Не путать с реальным состоянием — оно теперь живёт в листе `mailboxes`.

### Ключевые функции в checker.py (реальные имена, не как в старых заметках)

- `build_gmail(sa_path, subject_user)` — checker.py:166 — создаёт Gmail API клиент с impersonation (DWD); кэшируется в `gmail_clients` dict per-mailbox в `main()`.
- `tg_send(...)` — checker.py:184 — отправка в Telegram, уважает `dry_run` и `parse_mode`.
- `extract_text_preview(msg)` — checker.py:116 — текстовое превью письма (plain и html-парты, HTML-теги вырезаются).
- `strip_dotzero(val)` — checker.py:251 — убирает `.0` из чисел, которые Google Sheets/gspread возвращают как float (см. гочу ниже).
- `read_mailboxes_sheet(ws)` / `load_key_value_sheet(ws)` — парсинг листов `mailboxes` и `config`.
- `render_template` / `markdown_bold_to_html` — рендер `format.md` в HTML-текст для Telegram.

## Google Sheets — источник истины

Таблица (URL захардкожен в checker.py:357) — 3 листа: `config` (key/value), `mailboxes` (конфиг + routing + state по ящику), `events` (append-only лог). Подробное описание полей — в [README.md](README.md#google-sheets-структура).

## Гочи (non-obvious)

1. **Не кешировать** `config`/`mailboxes` вне тела цикла — оба листа перечитываются каждую итерацию (`main()` checker.py:432-449), это и есть hot-reload. Операционные переменные (`poll_s`, `max_results`, `bootstrap`, `tg_dry_run`, `allow_non_personal`) читаются из `os.environ` заново после каждого обновления config.
2. **Float-конвертация Sheets**: gspread отдаёт числа как float даже для ID-like строк (`-5012137290.0`) — всегда прогонять через `strip_dotzero()` перед использованием как chat_id/timestamp.
3. **tg_chat_id резолвинг** (checker.py:478-497): если значение начинается с `TG_CHAT_ID`/`CHAT_ID` — ищется в `os.environ` по трём вариантам (`raw`, `"TG_"+raw`, `raw` без префикса `TG_`), иначе используется как сырой ID. Фоллбэк — `TG_CHAT_ID_1`/`CHAT_ID_1`.
4. **Telegram guardrail**: если `tg_chat` начинается с `-` (группа/канал) и `TG_ALLOW_NON_PERSONAL != true` — сообщение блокируется молча (только в лог), проверяется на каждый ящик в каждом цикле.
5. **Parse mode — HTML, не MarkdownV2**: `**bold**` конвертируется в `<b>bold</b>` регэкспом (`markdown_bold_to_html`), а не через Telegram Markdown-парсер — он слишком хрупкий для динамического контента (subject/from из письма).
6. **Bootstrap** (`skip_existing` vs остальное, checker.py:536-559): `skip_existing` создаёт checkpoint из самого свежего кандидата и **не шлёт** ничего при первой инициализации ящика; любое другое значение помечает ящик initialized без checkpoint — тогда шлётся всё, что найдётся.
7. **last_sent_ids_json** хранит последние 50 ID отправленных писем — защита от дублей при одновременном совпадении по timestamp. `initialized` определяется исключительно как `last_internal_ms > 0` (см. `read_mailboxes_sheet`); чтобы вручную сбросить ящик, нужно очистить **оба** поля — `last_internal_ms` до `0` и `last_sent_ids_json` до `[]`. (До 2026-09-23 в коде был баг: пустой `last_sent_ids_json` сам по себе сбрасывал `initialized` каждый цикл — из-за этого `BOOTSTRAP=skip_existing` уходил в бесконечный цикл ре-бутстрапа для любого нового ящика: checkpoint переставлялся на новое письмо, но уведомление никогда не отправлялось, а `events` заполнялся `init_checkpoint`-строками каждый цикл. Убрано.)
8. **IMAP заблокирован** Google Workspace на этом домене — только Gmail API + Domain-Wide Delegation через `service_account_freelance.json`.
9. **Gmail API не помечает письма прочитанными** — это намеренное поведение, не баг.
10. **Локальные фоллбэк-пути захардкожены под Windows-машину разработчика**: `C:\Rubrain\Secrets\...` (checker.py:70, 358) — используются только если `env_loader` не смог найти `../secrets/` или `/secrets/`; в норме секреты приходят через `env_loader.py`.
11. **Subject matching** — Gmail query ищет `subject:"<phrase>"`, но после API-ответа код ещё раз проверяет точное вхождение фразы в заголовок (checker.py:526) — Gmail search не всегда 100% точен по подстроке.
12. **Автодеплой падает на SSH-рукопожатии** (`ssh: unable to authenticate, attempted methods [none publickey]` в логе GitHub Actions) — значит секрет `SSH_PRIVATE_KEY` репозитория не совпадает с ключами в `~/.ssh/authorized_keys` на сервере. Актуальный ключ — `~/.ssh/github_deploy` на сервере (тот же ключ зарегистрирован на GitHub-аккаунте `bi-smartbrain` как "ai-server", Read/write). См. [AGENTS.md](AGENTS.md#если-автодеплой-упал-на-ssh-рукопожатии).

## Частые задачи

- **Добавить ящик** — строка в лист `mailboxes` с `enabled=TRUE`. Перезапуск не нужен.
- **Изменить интервал** — `POLL_INTERVAL_SECONDS` в листе `config`. Подхватится на следующем цикле.
- **Сбросить состояние ящика** — очистить `last_internal_ms` до `0` **и** `last_sent_ids_json` до `[]` в `mailboxes` (нужны оба поля, см. гочу 7).
- **Отладка без спама в Telegram** — `TG_DRY_RUN=true` в `config`.
- **Поменять текст уведомления** — правь [format.md](format.md), перезапуск не нужен (перечитывается по mtime).

## Сервер и деплой

Подробности — в [AGENTS.md](AGENTS.md#сервер) и [AGENTS.md](AGENTS.md#cicd--автодеплой). Коротко: `git push origin master` → GitHub Actions → SSH на `root@bi.smartbrain.io` → `/opt/auto/update_GmailChecker.sh` (git pull → `docker compose up -d --build --remove-orphans`). Секреты на сервере — `/opt/secrets/`, монтируются в контейнер как `/secrets:ro`. На сервере установлен Docker Compose v2 как плагин (`docker compose`), не отдельный бинарник `docker-compose` — старые куски документации/скриптов с дефисом были ошибкой.
