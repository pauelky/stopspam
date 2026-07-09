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
- `/react 👌` ответом на сообщение.
- `/autoreact on`, `/autoreact off`, `/autoreact status`.
- `/say текст` одно сообщение в текущий чат.
- `/saytest 3 текст` только в Saved Messages.
- `/comands` или `/commands` список всех команд в Saved Messages.
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

## Clean Command

```text
/clean 10
/clean 20
```

Deletes the latest N messages in the current chat. Limit: 1-100 messages per command. The command is owner-only.

## Private Flood Guard

```text
/flood on
/flood off
/flood status
```

Works only in private chats. If a person sends more than 5 messages in 10 seconds, userbot enables auto-delete mute for that private chat. Daily mute ladder: 3 minutes, then 5 minutes, then 10 minutes. The ladder resets once per day.

Photo and video messages are ignored by the regular flood counter. Stickers have a separate rule: more than 1 sticker in 3 seconds triggers the same 3/5/10 minute mute ladder and deletes the stickers from that 3-second window.

## Sticker Block Per Chat

```text
/stickers on
/stickers off
/stickers status
```

This setting applies only to the chat where the command was written. When enabled, every incoming sticker in that chat is deleted immediately.

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

Список команд:

```text
/comands
/commands
```

Эта команда работает в Saved Messages и выводит все доступные команды userbot.

Реакции:

```text
/react 👌
/autoreact on
/autoreact off
/autoreact status
```

`/autoreact on` включает авторакции во всех чатах. Userbot ставит реакцию `👌` на входящие сообщения длиннее 40 символов и не чаще одного раза в 30 секунд.

Повторная отправка через `/say`:

```text
/say привет как дела 2
/say как ты 3
```

Последнее число считается количеством повторов. Максимум 10 повторов за одну команду.

## Ограничения

Telegram может не разрешить удалить некоторые сообщения, особенно в группах без нужных прав или в личных сообщениях “для всех”. В таких случаях userbot пробует удалить хотя бы у себя и пишет ошибку в лог, не падая.

Telegram также может запретить реакции в отдельных чатах. В таком случае userbot запишет ошибку в лог и продолжит работать.

Не используй userbot для спама или массовых рассылок. `/saytest` специально ограничен Saved Messages и максимум тремя сообщениями.
