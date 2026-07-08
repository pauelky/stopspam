from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta
from html import escape

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.custom.message import Message
from telethon.tl.types import User

from config import Config
from database import Database, from_iso, utc_now


log = logging.getLogger(__name__)
MUTE_RE = re.compile(r"^/mute\s+(\d+)(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
MUTEME_RE = re.compile(r"^/muteme\s+(\d+)(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)


def _is_owner(event: events.NewMessage.Event, config: Config) -> bool:
    return event.sender_id == config.owner_id


def _name(entity: object | None, fallback_id: int) -> str:
    if isinstance(entity, User):
        if entity.username:
            return f"@{entity.username}"
        full_name = " ".join(part for part in [entity.first_name, entity.last_name] if part)
        if full_name:
            return full_name
    return str(fallback_id)


def _username(entity: object | None) -> str:
    if isinstance(entity, User) and entity.username:
        return entity.username
    return ""


async def _delete_command(event: events.NewMessage.Event, db: Database) -> None:
    if not db.bool_setting("delete_command_messages", True):
        return
    try:
        await event.delete()
    except RPCError:
        log.debug("Could not delete command message", exc_info=True)


async def _delete_messages_safe(client: TelegramClient, chat_id: int, message_ids: list[int]) -> int:
    if not message_ids:
        return 0
    try:
        await client.delete_messages(chat_id, message_ids, revoke=True)
        return len(message_ids)
    except FloodWaitError as exc:
        log.warning("Flood wait while deleting messages: %s seconds", exc.seconds)
        await asyncio.sleep(min(exc.seconds, 60))
    except RPCError:
        log.warning("Could not delete messages with revoke=True", exc_info=True)

    try:
        await client.delete_messages(chat_id, message_ids, revoke=False)
        return len(message_ids)
    except RPCError:
        log.warning("Could not delete messages with revoke=False", exc_info=True)
        return 0


async def _clean_old_messages(
    client: TelegramClient,
    db: Database,
    chat_id: int,
    user_id: int,
    limit: int,
) -> int:
    message_ids: list[int] = []
    try:
        async for message in client.iter_messages(chat_id, from_user=user_id, limit=limit):
            message_ids.append(message.id)
    except RPCError:
        log.warning("Could not fetch old messages for cleanup", exc_info=True)
        return 0

    deleted = await _delete_messages_safe(client, chat_id, message_ids)
    if deleted:
        db.add_cleaned_old(chat_id, user_id, deleted)
    return deleted


async def _reply_target(event: events.NewMessage.Event) -> tuple[Message | None, int | None, object | None]:
    reply = await event.get_reply_message()
    if not reply or not reply.sender_id:
        return None, None, None
    sender = await reply.get_sender()
    return reply, int(reply.sender_id), sender


async def handle_mute(event: events.NewMessage.Event, client: TelegramClient, db: Database, config: Config) -> None:
    if not _is_owner(event, config):
        return

    match = MUTE_RE.match(event.raw_text or "")
    if not match:
        return

    reply, user_id, sender = await _reply_target(event)
    if reply is None or user_id is None:
        await event.respond("Ответь командой /mute на сообщение пользователя.\nПример: /mute 10")
        await _delete_command(event, db)
        return

    minutes = int(match.group(1))
    reason_raw = (match.group(2) or "").strip()
    clean = "--clean" in reason_raw.split()
    reason = " ".join(part for part in reason_raw.split() if part != "--clean").strip()
    reason = reason or "не указана"
    muted_until = utc_now() + timedelta(minutes=minutes)

    chat_id = int(event.chat_id)
    db.upsert_mute(
        chat_id=chat_id,
        user_id=user_id,
        username=_username(sender),
        duration_minutes=minutes,
        reason=reason,
        muted_until=muted_until,
    )

    cleaned = 0
    if clean:
        clean_limit = int(db.get_setting("clean_limit", str(config.clean_limit)) or config.clean_limit)
        cleaned = await _clean_old_messages(client, db, chat_id, user_id, clean_limit)

    db.add_log(
        "mute",
        {
            "chat_id": chat_id,
            "user_id": user_id,
            "minutes": minutes,
            "reason": reason,
            "cleaned_old": cleaned,
        },
    )
    log.info("Muted user %s in chat %s for %s minutes", user_id, chat_id, minutes)

    target_name = _name(sender, user_id)
    first_message = (
        f"{target_name}, вы замьючены на {minutes} мин.\n"
        "Новые сообщения на время мьюта будут удаляться автоматически."
    )
    if clean:
        first_message += f"\nУдалено старых сообщений: {cleaned}."
    await event.respond(first_message)
    await event.respond(f"Причина: <b>{escape(reason)}</b>", parse_mode="html")
    await _delete_command(event, db)
    return

    if clean:
        text = (
            f"OK. Пользователь {_name(sender, user_id)} замьючен на {minutes} минут.\n"
            f"Удалено старых сообщений: {cleaned}.\n"
            "Новые сообщения будут удаляться автоматически."
        )
    else:
        text = (
            f"OK. Пользователь {_name(sender, user_id)} замьючен на {minutes} минут.\n"
            "Режим: автоудаление сообщений.\n"
            f"Причина: {reason}."
        )
    await event.respond(text)
    await _delete_command(event, db)


async def handle_unmute(event: events.NewMessage.Event, db: Database, config: Config) -> None:
    if not _is_owner(event, config) or (event.raw_text or "").strip().lower() != "/unmute":
        return

    _, user_id, sender = await _reply_target(event)
    if user_id is None:
        await event.respond("Ответь командой /unmute на сообщение пользователя.")
        await _delete_command(event, db)
        return

    changed = db.deactivate_mute(int(event.chat_id), user_id)
    if changed:
        db.add_log("unmute", {"chat_id": int(event.chat_id), "user_id": user_id})
        await event.respond(
            f"OK. Пользователь {_name(sender, user_id)} размьючен.\n"
            "Его новые сообщения больше не будут удаляться."
        )
    else:
        await event.respond("У этого пользователя нет активного мьюта в этом чате.")
    await _delete_command(event, db)


async def handle_mutes(event: events.NewMessage.Event, db: Database, config: Config) -> None:
    if not _is_owner(event, config) or (event.raw_text or "").strip().lower() != "/mutes":
        return

    rows = db.list_active_mutes(int(event.chat_id))
    if not rows:
        await event.respond("В этом чате нет активных мьютов.")
        await _delete_command(event, db)
        return

    lines = ["Активные мьюты в этом чате:"]
    for index, row in enumerate(rows, start=1):
        until = from_iso(row["muted_until"]).astimezone().strftime("%H:%M")
        name = f"@{row['username']}" if row["username"] else str(row["user_id"])
        lines.append(
            f"{index}. {name}\n"
            f"   До: {until}\n"
            f"   Причина: {row['reason']}\n"
            f"   Удалено сообщений: {row['deleted_count']}"
        )

    await event.respond("\n\n".join(lines))
    await _delete_command(event, db)


async def handle_muteme(event: events.NewMessage.Event, db: Database, config: Config) -> None:
    if not _is_owner(event, config):
        return
    match = MUTEME_RE.match(event.raw_text or "")
    if not match:
        return
    if not event.is_private:
        await event.respond("В группе используй /mute ответом на сообщение пользователя.")
        await _delete_command(event, db)
        return
    if int(event.chat_id) == config.owner_id:
        await event.respond("В Saved Messages нельзя замьютить самого себя.")
        await _delete_command(event, db)
        return

    minutes = int(match.group(1))
    reason = (match.group(2) or "").strip() or "не указана"
    chat_id = int(event.chat_id)
    user_id = int(event.chat_id)
    entity = await event.get_chat()
    db.upsert_mute(
        chat_id=chat_id,
        user_id=user_id,
        username=_username(entity),
        duration_minutes=minutes,
        reason=reason,
        muted_until=utc_now() + timedelta(minutes=minutes),
    )
    await event.respond(
        f"OK. Собеседник {_name(entity, user_id)} замьючен на {minutes} минут.\n"
        "Новые сообщения будут удаляться автоматически."
    )
    await _delete_command(event, db)


async def handle_unmuteme(event: events.NewMessage.Event, db: Database, config: Config) -> None:
    if not _is_owner(event, config) or (event.raw_text or "").strip().lower() != "/unmuteme":
        return
    if not event.is_private:
        await event.respond("В группе используй /unmute ответом на сообщение пользователя.")
        await _delete_command(event, db)
        return
    changed = db.deactivate_mute(int(event.chat_id), int(event.chat_id))
    if changed:
        await event.respond("OK. Собеседник размьючен.")
    else:
        await event.respond("В этой личке нет активного мьюта.")
    await _delete_command(event, db)


async def handle_incoming_for_mute(event: events.NewMessage.Event, db: Database) -> None:
    if event.out or not event.sender_id or not event.chat_id:
        return
    row = db.active_mute(int(event.chat_id), int(event.sender_id))
    if row is None:
        return

    deleted = await _delete_messages_safe(event.client, int(event.chat_id), [event.message.id])
    if deleted:
        db.increment_deleted(
            mute_id=int(row["id"]),
            chat_id=int(event.chat_id),
            user_id=int(event.sender_id),
            message_id=event.message.id,
            reason="active_mute",
        )
        db.add_log(
            "auto_delete",
            {"chat_id": int(event.chat_id), "user_id": int(event.sender_id), "message_id": event.message.id},
        )
        log.info("Auto-deleted message %s from user %s", event.message.id, event.sender_id)


async def expire_mutes_loop(client: TelegramClient, db: Database, config: Config) -> None:
    while True:
        try:
            rows = db.expire_old_mutes()
            for row in rows:
                db.add_log("mute_expired", {"chat_id": row["chat_id"], "user_id": row["user_id"]})
                log.info("Mute expired for user %s in chat %s", row["user_id"], row["chat_id"])
                if db.bool_setting("notify_mute_expired", False):
                    name = f"@{row['username']}" if row["username"] else str(row["user_id"])
                    await client.send_message(row["chat_id"], f"Мьют пользователя {name} закончился.")
        except FloodWaitError as exc:
            log.warning("Flood wait in expire loop: %s seconds", exc.seconds)
            await asyncio.sleep(min(exc.seconds, 60))
        except Exception:
            log.exception("Mute expiration loop failed")
        await asyncio.sleep(config.expire_check_seconds)


def register_cleaner_mute(client: TelegramClient, db: Database, config: Config) -> None:
    @client.on(events.NewMessage(pattern=r"^/mute(?:\s|$)"))
    async def _mute(event: events.NewMessage.Event) -> None:
        await handle_mute(event, client, db, config)

    @client.on(events.NewMessage(pattern=r"^/unmute$"))
    async def _unmute(event: events.NewMessage.Event) -> None:
        await handle_unmute(event, db, config)

    @client.on(events.NewMessage(pattern=r"^/mutes$"))
    async def _mutes(event: events.NewMessage.Event) -> None:
        await handle_mutes(event, db, config)

    @client.on(events.NewMessage(pattern=r"^/muteme(?:\s|$)"))
    async def _muteme(event: events.NewMessage.Event) -> None:
        await handle_muteme(event, db, config)

    @client.on(events.NewMessage(pattern=r"^/unmuteme$"))
    async def _unmuteme(event: events.NewMessage.Event) -> None:
        await handle_unmuteme(event, db, config)

    @client.on(events.NewMessage(incoming=True))
    async def _auto_delete(event: events.NewMessage.Event) -> None:
        await handle_incoming_for_mute(event, db)
