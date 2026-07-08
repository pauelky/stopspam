from __future__ import annotations

import logging
from datetime import timedelta

from telethon import TelegramClient, events
from telethon.errors import RPCError
from telethon.tl.types import User

from config import Config
from database import Database, utc_now


log = logging.getLogger(__name__)
FLOOD_LIMIT = 5
FLOOD_WINDOW_SECONDS = 10


def _is_owner(event: events.NewMessage.Event, config: Config) -> bool:
    return event.sender_id == config.owner_id


def _username(entity: object | None) -> str:
    if isinstance(entity, User) and entity.username:
        return entity.username
    return ""


async def handle_flood_command(event: events.NewMessage.Event, db: Database, config: Config) -> None:
    if not _is_owner(event, config):
        return

    text = (event.raw_text or "").strip().lower()
    parts = text.split()
    action = parts[1] if len(parts) > 1 else "status"

    if action == "on":
        db.set_setting("flood_enabled", "true")
        db.add_log("flood_on", {"chat_id": int(event.chat_id or 0)})
        await event.respond(
            "OK. Антифлуд включен для всех личных чатов.\n"
            "Правило: больше 5 сообщений за 10 секунд.\n"
            "Мьюты за день: 3 мин, потом 5 мин, потом 10 мин."
        )
    elif action == "off":
        db.set_setting("flood_enabled", "false")
        db.add_log("flood_off", {"chat_id": int(event.chat_id or 0)})
        await event.respond("OK. Антифлуд выключен.")
    elif action == "status":
        status = "включен" if db.bool_setting("flood_enabled", False) else "выключен"
        await event.respond(
            f"Антифлуд: {status}\n"
            "Область: только личные чаты\n"
            "Порог: больше 5 сообщений за 10 секунд\n"
            "Мьюты: 3/5/10 минут, сброс раз в сутки"
        )
    else:
        await event.respond("Использование: /flood on | off | status")


async def handle_private_flood(event: events.NewMessage.Event, db: Database) -> None:
    if event.out or not event.is_private or not event.chat_id or not event.sender_id:
        return
    if not db.bool_setting("flood_enabled", False):
        return
    if db.active_mute(int(event.chat_id), int(event.sender_id)) is not None:
        return

    message_count = db.add_flood_event(
        chat_id=int(event.chat_id),
        user_id=int(event.sender_id),
        message_id=event.message.id,
        window_seconds=FLOOD_WINDOW_SECONDS,
    )
    if message_count <= FLOOD_LIMIT:
        return

    penalty_count, mute_minutes = db.next_flood_penalty(int(event.chat_id), int(event.sender_id))
    sender = await event.get_sender()
    reason = f"флуд: {message_count} сообщений за {FLOOD_WINDOW_SECONDS} секунд"
    db.upsert_mute(
        chat_id=int(event.chat_id),
        user_id=int(event.sender_id),
        username=_username(sender),
        duration_minutes=mute_minutes,
        reason=reason,
        muted_until=utc_now() + timedelta(minutes=mute_minutes),
    )
    db.add_log(
        "flood_mute",
        {
            "chat_id": int(event.chat_id),
            "user_id": int(event.sender_id),
            "message_count": message_count,
            "penalty_count": penalty_count,
            "mute_minutes": mute_minutes,
        },
    )
    log.info(
        "Flood-muted user %s in private chat %s for %s minutes",
        event.sender_id,
        event.chat_id,
        mute_minutes,
    )
    try:
        await event.delete()
    except RPCError:
        log.debug("Could not delete flood trigger message", exc_info=True)
    await event.respond(
        f"Антифлуд: авто-мьют на {mute_minutes} мин.\n"
        "Новые сообщения временно будут удаляться автоматически."
    )


def register_flood_guard(client: TelegramClient, db: Database, config: Config) -> None:
    @client.on(events.NewMessage(pattern=r"^/flood(?:\s|$)"))
    async def _flood_command(event: events.NewMessage.Event) -> None:
        await handle_flood_command(event, db, config)

    @client.on(events.NewMessage(incoming=True))
    async def _private_flood(event: events.NewMessage.Event) -> None:
        await handle_private_flood(event, db)
