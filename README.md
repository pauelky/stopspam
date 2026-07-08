# Telegram Chat Cleaner Userbot

Отдельный Telegram userbot на Python и Telethon. Работает через твой Telegram-аккаунт, `.session` файл и удаляет новые сообщения замьюченных пользователей в конкретном чате.

## Возможности

- `/mute 10` ответом на сообщение: автоудаление новых сообщений пользователя 10 минут.
- `/mute 10 причина` и `/mute 10 --clean причина`.
- `/unmute` ответом на сообщение.
- `/mutes` список активных мьютов в текущем чате.
- `/muteme 10` и `/unmuteme` в личных сообщениях.
- `/read on`, `/read off`, `/read status`.
- `/readblacklist add`, `/readblacklist remove`, `/readblacklist list`.
- `/say текст` одно сообщение в текущий чат.
- `/saytest 3 текст` только в Saved Messages.
- SQLite, файл логов, Docker.

Все команды выполняются только от `OWNER_ID`.

## Настройка

1. Получи `API_ID` и `API_HASH` на [my.telegram.org](https://my.telegram.org).
2. Скопируй `.env.example` в `.env`.
3. Заполни:

```dotenv
API_ID=
API_HASH=
SESSION_NAME=chat_cleaner
OWNER_ID=
DATABASE_PATH=./data/bot.db
CLEAN_LIMIT=50
LOG_PATH=./logs/app.log
EXPIRE_CHECK_SECONDS=45
```

`OWNER_ID` должен быть ID того Telegram-аккаунта, под которым авторизуется userbot.

## Локальный запуск

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

При первом запуске Telethon попросит телефон, код Telegram и, если включено, пароль 2FA. Сессия сохранится в `sessions/chat_cleaner.session`.

## Docker

Первый интерактивный запуск для создания session-файла:

```bash
docker compose run --rm telegram-chat-cleaner
```

После успешной авторизации:

```bash
docker compose up -d
docker logs -f telegram-chat-cleaner
```

`sessions/`, `data/` и `logs/` подключены как volume, поэтому session, база и логи не пропадут после перезапуска контейнера.

## Примеры

В группе или личке ответом на сообщение пользователя:

```text
/mute 10 спам
```

После этого новые сообщения этого пользователя удаляются только в текущем чате.

Снять мьют:

```text
/unmute
```

Показать активные мьюты:

```text
/mutes
```

В личке без reply:

```text
/muteme 10
/unmuteme
```

Авточтение:

```text
/read on
/read off
/read status
```

## Ограничения

Telegram может не разрешить удалить некоторые сообщения, особенно в группах без нужных прав или в личных сообщениях “для всех”. В таких случаях userbot пробует удалить хотя бы у себя и пишет ошибку в лог, не падая.

Не используй userbot для спама или массовых рассылок. `/saytest` специально ограничен Saved Messages и максимум тремя сообщениями.
