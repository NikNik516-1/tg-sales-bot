import asyncio
import sys
import time
from logger import setup
from pyrogram import Client
from config import TG_API_ID, TG_API_HASH, TG_SESSION_STRING, TG_PROXY_HOST, TG_PROXY_PORT
import chat_manager
import listener
import rag
import user_profile

log = setup("bot")

_CONNECT_TIMEOUT = 5 * 60    # сек до выхода если не подключились
_RECONNECT_TIMEOUT = 10 * 60  # сек до выхода если потеряли соединение


async def _reload_chats_loop():
    while True:
        await asyncio.sleep(60)
        try:
            await chat_manager.reload()
        except Exception as e:
            log.error("ошибка перезагрузки чатов", error=str(e))


async def _connection_watchdog(app: Client):
    disconnected_since: float | None = None
    while True:
        await asyncio.sleep(30)
        if app.is_connected:
            disconnected_since = None
        else:
            if disconnected_since is None:
                disconnected_since = time.monotonic()
                log.warning("потеря соединения с Telegram")
            elif time.monotonic() - disconnected_since > _RECONNECT_TIMEOUT:
                log.error("не удалось восстановить соединение, перезапуск", timeout=_RECONNECT_TIMEOUT)
                sys.exit(1)


async def main():
    log.info("инициализация RAG")
    rag.init()
    user_profile.load()

    log.info("загрузка списка групп")
    await chat_manager.load()

    log.info("подключение к Telegram")
    proxy = {"scheme": "socks5", "hostname": TG_PROXY_HOST, "port": TG_PROXY_PORT} if TG_PROXY_HOST else None
    tg_app = Client(
        "seller",
        api_id=TG_API_ID,
        api_hash=TG_API_HASH,
        session_string=TG_SESSION_STRING,
        proxy=proxy,
    )
    listener.register(tg_app)

    try:
        await asyncio.wait_for(tg_app.start(), timeout=_CONNECT_TIMEOUT)
    except asyncio.TimeoutError:
        log.error("timeout подключения к Telegram, перезапуск", timeout=_CONNECT_TIMEOUT)
        sys.exit(1)

    try:
        me = await tg_app.get_me()
        log.info("telegram запущен", username=me.username, tg_id=me.id)
        log.info("слушаю сообщения")

        asyncio.create_task(_reload_chats_loop())
        asyncio.create_task(_connection_watchdog(tg_app))
        await asyncio.Event().wait()
    finally:
        await tg_app.stop()


if __name__ == "__main__":
    asyncio.run(main())
