from __future__ import annotations

import logging
from datetime import UTC, datetime

from telethon import TelegramClient, events, functions, types
from telethon.errors import FloodWaitError, RPCError

from config import Config
from database import Database, from_iso


log = logging.getLogger(__name__)
DEFAULT_REACTION = "👌"
DEFAULT_MIN_CHARS = 40
DEFAULT_COOLDOWN_SECONDS = 30


def _is_owner(event: events.NewMessage.Event, config: Config) -> bool:
    return event.sender_id == config.owner_id


def _message_text(event: events.NewMessage.Event) -> str:
    return (event.raw_text or "").strip()


async def _send_reaction(client: TelegramClient, chat_id: int, message_id: int, emoji: str) -> None:
    await client(
        functions.messages.SendReactionRequest(
            peer=chat_id,
            msg_id=message_id,
            reaction=[types.ReactionEmoji(emoticon=emoji)],
            big=False,
            add_to_recent=True,
        )
    )


async def handle_react_command(event: events.NewMessage.Event, client: TelegramClient, config: Config) -> None:
    if not _is_owner(event, config):
        return
    text = _message_text(event)
    if not text.startswith("/react"):
        return

    parts = text.split(maxsplit=1)
    emoji = parts[1].strip() if len(parts) > 1 else DEFAULT_REACTION
    reply = await event.get_reply_message()
    if not reply:
        await event.respond("Ответь /react 👌 на сообщение, куда нужно поставить реакцию.")
        return

    try:
        await _send_reaction(client, int(event.chat_id), reply.id, emoji)
        await event.respond(f"OK. Реакция {emoji} поставлена.")
    except FloodWaitError as exc:
        log.warning("Flood wait while sending manual reaction: %s seconds", exc.seconds)
        await event.respond(f"Telegram просит подождать {exc.seconds} сек.")
    except RPCError:
        log.warning("Could not send manual reaction", exc_info=True)
        await event.respond("Не получилось поставить реакцию. Возможно, реакции в этом чате запрещены.")


async def handle_autoreact_command(event: events.NewMessage.Event, db: Database, config: Config) -> None:
    if not _is_owner(event, config):
        return

    text = _message_text(event).lower()
    if not text.startswith("/autoreact"):
        return

    parts = text.split()
    action = parts[1] if len(parts) > 1 else "status"
    chat_id = int(event.chat_id)

    if action == "on":
        db.set_auto_reaction(
            chat_id=chat_id,
            enabled=True,
            emoji=DEFAULT_REACTION,
            min_chars=DEFAULT_MIN_CHARS,
            cooldown_seconds=DEFAULT_COOLDOWN_SECONDS,
        )
        await event.respond(
            f"OK. Авторакция включена в этом чате.\n"
            f"Условие: сообщения длиннее {DEFAULT_MIN_CHARS} символов.\n"
            f"Реакция: {DEFAULT_REACTION}."
        )
    elif action == "off":
        row = db.get_auto_reaction(chat_id)
        emoji = row["emoji"] if row else DEFAULT_REACTION
        min_chars = int(row["min_chars"]) if row else DEFAULT_MIN_CHARS
        cooldown = int(row["cooldown_seconds"]) if row else DEFAULT_COOLDOWN_SECONDS
        db.set_auto_reaction(chat_id, False, emoji, min_chars, cooldown)
        await event.respond("OK. Авторакция выключена в этом чате.")
    elif action == "status":
        row = db.get_auto_reaction(chat_id)
        if not row or not row["enabled"]:
            await event.respond("Авторакция в этом чате: выключена.")
        else:
            await event.respond(
                "Авторакция в этом чате: включена.\n"
                f"Реакция: {row['emoji']}\n"
                f"Минимум символов: {row['min_chars']}\n"
                f"Cooldown: {row['cooldown_seconds']} сек."
            )
    else:
        await event.respond("Использование: /autoreact on | off | status")


async def handle_auto_reaction(event: events.NewMessage.Event, client: TelegramClient, db: Database) -> None:
    if event.out or not event.chat_id or not event.sender_id:
        return

    text = _message_text(event)
    if not text or text.startswith("/") or len(text) <= DEFAULT_MIN_CHARS:
        return

    row = db.get_auto_reaction(int(event.chat_id))
    if not row or not row["enabled"]:
        return

    min_chars = int(row["min_chars"])
    if len(text) <= min_chars:
        return

    last_reacted_at = row["last_reacted_at"]
    if last_reacted_at:
        elapsed = (datetime.now(UTC) - from_iso(last_reacted_at)).total_seconds()
        if elapsed < int(row["cooldown_seconds"]):
            return

    emoji = row["emoji"]
    try:
        await _send_reaction(client, int(event.chat_id), event.message.id, emoji)
        db.touch_auto_reaction(int(event.chat_id), int(event.sender_id), event.message.id, emoji)
        db.add_log(
            "auto_reaction",
            {
                "chat_id": int(event.chat_id),
                "user_id": int(event.sender_id),
                "message_id": event.message.id,
                "emoji": emoji,
            },
        )
    except FloodWaitError as exc:
        log.warning("Flood wait while sending auto reaction: %s seconds", exc.seconds)
    except RPCError:
        log.warning("Could not send auto reaction", exc_info=True)


def register_reactions(client: TelegramClient, db: Database, config: Config) -> None:
    @client.on(events.NewMessage(pattern=r"^/react(?:\s|$)"))
    async def _react(event: events.NewMessage.Event) -> None:
        await handle_react_command(event, client, config)

    @client.on(events.NewMessage(pattern=r"^/autoreact(?:\s|$)"))
    async def _autoreact(event: events.NewMessage.Event) -> None:
        await handle_autoreact_command(event, db, config)

    @client.on(events.NewMessage(incoming=True))
    async def _auto_reaction(event: events.NewMessage.Event) -> None:
        await handle_auto_reaction(event, client, db)
