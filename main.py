from __future__ import annotations

import asyncio
import logging

from telethon import TelegramClient

from config import load_config
from database import Database
from modules.auto_reader import register_auto_reader
from modules.cleaner_mute import expire_mutes_loop, register_cleaner_mute
from modules.logger import setup_logging
from modules.reactions import register_reactions
from modules.settings import register_settings


async def main() -> None:
    config = load_config()
    setup_logging(config.log_path)
    log = logging.getLogger(__name__)

    db = Database(config.database_path, config.clean_limit)
    log.info("Starting Telegram Chat Cleaner Userbot")

    client = TelegramClient(str(config.session_path), config.api_id, config.api_hash)
    await client.start()

    me = await client.get_me()
    log.info("Connected to Telegram as id=%s username=%s", me.id, me.username)
    if me.id != config.owner_id:
        log.warning(
            "OWNER_ID=%s differs from authorized account id=%s. Commands from this account may be ignored.",
            config.owner_id,
            me.id,
        )

    register_cleaner_mute(client, db, config)
    register_auto_reader(client, db, config)
    register_reactions(client, db, config)
    register_settings(client, db, config)

    asyncio.create_task(expire_mutes_loop(client, db, config))
    log.info("Userbot is running")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
