from __future__ import annotations

import asyncio
import logging
import re

from telethon import TelegramClient, events

from config import Config
from database import Database


log = logging.getLogger(__name__)
SAY_RE = re.compile(r"^/say\s+(.+)$", re.IGNORECASE | re.DOTALL)
SAYTEST_RE = re.compile(r"^/saytest\s+(\d+)\s+(.+)$", re.IGNORECASE | re.DOTALL)
COMMANDS_TEXT = """Команды userbot:

Мьюты:
/mute 10 - замьютить пользователя на 10 минут, ответом на сообщение
/mute 10 причина - замьютить с причиной
/mute 10 --clean причина - замьютить и удалить последние сообщения пользователя
/unmute - снять мьют, ответом на сообщение
/mutes - показать активные мьюты в текущем чате

Личные сообщения:
/muteme 10 - замьютить текущего собеседника в личке
/unmuteme - снять мьют с текущего собеседника

Авточтение:
/read on - включить автопрочтение
/read off - выключить автопрочтение
/read status - показать статус автопрочтения
/readblacklist add - добавить текущий чат или собеседника в blacklist
/readblacklist remove - убрать текущий чат или собеседника из blacklist
/readblacklist list - показать blacklist

Реакции:
/react 👌 - поставить реакцию ответом на сообщение
/autoreact on - включить реакцию 👌 на сообщения длиннее 40 символов
/autoreact off - выключить авторакцию в текущем чате
/autoreact status - показать статус авторакции

Сообщения:
/say текст - отправить одно сообщение в текущий чат
/saytest 3 текст - тест до 3 сообщений только в Saved Messages

Справка:
/comands - показать этот список в Saved Messages
/commands - то же самое
"""


COMMANDS_TEXT_SUFFIX = """

Обновления:
/autoreact on - включает реакцию 👌 на длинные входящие сообщения во всех чатах
/autoreact off - выключает авторакции во всех чатах
/say привет как дела 2 - отправить фразу 2 раза
/say как ты 3 - отправить фразу 3 раза

Для /say последнее число считается количеством повторов. Максимум 10.
"""


def _is_owner(event: events.NewMessage.Event, config: Config) -> bool:
    return event.sender_id == config.owner_id


async def handle_say(event: events.NewMessage.Event, db: Database, config: Config) -> None:
    if not _is_owner(event, config):
        return
    match = SAY_RE.match(event.raw_text or "")
    if not match:
        return
    text = match.group(1).strip()
    if text:
        phrase = text
        repeat_count = 1
        parts = text.rsplit(maxsplit=1)
        if len(parts) == 2 and parts[1].isdigit():
            phrase = parts[0].strip()
            repeat_count = int(parts[1])
        if not phrase:
            await event.respond("Использование: /say текст 2")
            return
        if repeat_count < 1 or repeat_count > 10:
            await event.respond("Для /say можно указать от 1 до 10 повторов.")
            return
        try:
            await event.delete()
        except Exception:
            log.debug("Could not delete /say command", exc_info=True)
        for index in range(repeat_count):
            await event.client.send_message(event.chat_id, phrase)
            if index + 1 < repeat_count:
                await asyncio.sleep(1)
        db.add_log(
            "say",
            {
                "chat_id": int(event.chat_id or 0),
                "length": len(phrase),
                "repeat_count": repeat_count,
            },
        )
        return
    if not text:
        await event.respond("Использование: /say текст")
        return
    try:
        await event.delete()
    except Exception:
        log.debug("Could not delete /say command", exc_info=True)
    await event.client.send_message(event.chat_id, text)
    db.add_log("say", {"chat_id": int(event.chat_id or 0), "length": len(text)})


async def handle_saytest(event: events.NewMessage.Event, client: TelegramClient, db: Database, config: Config) -> None:
    if not _is_owner(event, config):
        return
    match = SAYTEST_RE.match(event.raw_text or "")
    if not match:
        return
    if not event.is_private or int(event.chat_id) != config.owner_id:
        await event.respond("Команда /saytest работает только в Saved Messages или личном чате с собой.")
        return

    count = int(match.group(1))
    if count < 1 or count > 3:
        await event.respond("Для /saytest можно отправить от 1 до 3 сообщений.")
        return
    text = match.group(2).strip()
    if not text:
        await event.respond("Использование: /saytest 3 текст")
        return

    for _ in range(count):
        await client.send_message("me", text)
        await asyncio.sleep(2)
    db.add_log("saytest", {"count": count, "length": len(text)})


async def handle_commands(event: events.NewMessage.Event, config: Config) -> None:
    if not _is_owner(event, config):
        return
    text = (event.raw_text or "").strip().lower()
    if text not in {"/comands", "/commands"}:
        return
    if not event.is_private or int(event.chat_id) != config.owner_id:
        await event.respond("Команда /comands работает только в Saved Messages.")
        return
    await event.respond(COMMANDS_TEXT + COMMANDS_TEXT_SUFFIX)


def register_settings(client: TelegramClient, db: Database, config: Config) -> None:
    @client.on(events.NewMessage(pattern=r"^/(?:comands|commands)$"))
    async def _commands(event: events.NewMessage.Event) -> None:
        await handle_commands(event, config)

    @client.on(events.NewMessage(pattern=r"^/say(?:\s|$)"))
    async def _say(event: events.NewMessage.Event) -> None:
        await handle_say(event, db, config)

    @client.on(events.NewMessage(pattern=r"^/saytest(?:\s|$)"))
    async def _saytest(event: events.NewMessage.Event) -> None:
        await handle_saytest(event, client, db, config)
