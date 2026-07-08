from __future__ import annotations

import logging

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError

from config import Config
from database import Database


log = logging.getLogger(__name__)


def _is_owner(event: events.NewMessage.Event, config: Config) -> bool:
    return event.sender_id == config.owner_id


async def handle_read_command(event: events.NewMessage.Event, db: Database, config: Config) -> None:
    if not _is_owner(event, config):
        return

    text = (event.raw_text or "").strip().lower()
    if text == "/read on":
        db.set_setting("auto_read_enabled", "true")
        db.add_log("auto_read_on", {"chat_id": int(event.chat_id or 0)})
        await event.respond(
            "OK. Авточтение включено.\n"
            "Теперь входящие сообщения будут помечаться как прочитанные."
        )
    elif text == "/read off":
        db.set_setting("auto_read_enabled", "false")
        db.add_log("auto_read_off", {"chat_id": int(event.chat_id or 0)})
        await event.respond("OK. Авточтение выключено.")
    elif text == "/read status":
        status = "включено" if db.bool_setting("auto_read_enabled", False) else "выключено"
        await event.respond(
            f"Авточтение: {status}\n"
            f"Прочитано сообщений сегодня: {db.read_count_today()}"
        )


async def handle_read_blacklist(event: events.NewMessage.Event, db: Database, config: Config) -> None:
    if not _is_owner(event, config):
        return

    text = (event.raw_text or "").strip().lower()
    if not text.startswith("/readblacklist"):
        return
    parts = text.split()
    action = parts[1] if len(parts) > 1 else ""

    if action == "add":
        if event.is_private:
            if int(event.chat_id) == config.owner_id:
                await event.respond("Saved Messages не добавляется в blacklist.")
                return
            db.add_read_blacklist(chat_id=None, user_id=int(event.chat_id), item_type="user")
            await event.respond("OK. Собеседник добавлен в read-blacklist.")
        else:
            db.add_read_blacklist(chat_id=int(event.chat_id), user_id=None, item_type="chat")
            await event.respond("OK. Текущий чат добавлен в read-blacklist.")
    elif action == "remove":
        if event.is_private:
            changed = db.remove_read_blacklist(chat_id=None, user_id=int(event.chat_id), item_type="user")
        else:
            changed = db.remove_read_blacklist(chat_id=int(event.chat_id), user_id=None, item_type="chat")
        await event.respond("OK. Удалено из read-blacklist." if changed else "Этого элемента не было в read-blacklist.")
    elif action == "list":
        rows = db.list_read_blacklist()
        if not rows:
            await event.respond("Read-blacklist пуст.")
            return
        lines = ["Read-blacklist:"]
        for row in rows:
            if row["type"] == "chat":
                lines.append(f"- chat_id={row['chat_id']}")
            else:
                lines.append(f"- user_id={row['user_id']}")
        await event.respond("\n".join(lines))
    else:
        await event.respond("Использование: /readblacklist add | remove | list")


async def handle_auto_read(event: events.NewMessage.Event, client: TelegramClient, db: Database) -> None:
    if event.out or not event.chat_id:
        return
    if not db.bool_setting("auto_read_enabled", False):
        return
    user_id = int(event.sender_id or 0)
    if db.is_read_blacklisted(int(event.chat_id), user_id or None):
        return

    try:
        await client.send_read_acknowledge(event.chat_id, max_id=event.message.id)
        db.add_read_log(int(event.chat_id), user_id, event.message.id)
        db.add_log(
            "auto_read",
            {"chat_id": int(event.chat_id), "user_id": user_id, "message_id": event.message.id},
        )
        log.info("Marked message %s in chat %s as read", event.message.id, event.chat_id)
    except FloodWaitError as exc:
        log.warning("Flood wait while marking read: %s seconds", exc.seconds)
    except RPCError:
        log.warning("Could not mark message as read", exc_info=True)


def register_auto_reader(client: TelegramClient, db: Database, config: Config) -> None:
    @client.on(events.NewMessage(pattern=r"^/read(?:\s|$)"))
    async def _read_command(event: events.NewMessage.Event) -> None:
        await handle_read_command(event, db, config)

    @client.on(events.NewMessage(pattern=r"^/readblacklist(?:\s|$)"))
    async def _read_blacklist(event: events.NewMessage.Event) -> None:
        await handle_read_blacklist(event, db, config)

    @client.on(events.NewMessage(incoming=True))
    async def _auto_read(event: events.NewMessage.Event) -> None:
        await handle_auto_read(event, client, db)
