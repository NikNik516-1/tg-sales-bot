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

_CONNECT_TIMEOUT = 5 * 60     # сек до выхода если не подключились при старте
_WATCHDOG_INTERVAL = 60       # секунд между проверками связи
_WATCHDOG_FAIL_TIMEOUT = 600  # 10 минут без связи → выйти (Docker перезапустит)


async def _reload_chats_loop():
    while True:
        await asyncio.sleep(60)
        try:
            await chat_manager.reload()
        except Exception as e:
            log.error("ошибка перезагрузки чатов", error=str(e))


async def _watchdog_loop(tg_app: Client):
    # Активный пинг через get_me() надёжнее is_connected:
    # обнаруживает зомби-соединения (TCP жив, но данные не ходят)
    await asyncio.sleep(60)  # дать время на первоначальный старт
    failed_since: float | None = None
    while True:
        await asyncio.sleep(_WATCHDOG_INTERVAL)
        try:
            await asyncio.wait_for(tg_app.get_me(), timeout=20)
            if failed_since is not None:
                log.info("watchdog: соединение восстановлено")
            failed_since = None
        except Exception as e:
            now = time.monotonic()
            if failed_since is None:
                failed_since = now
                log.warning("watchdog: нет связи с Telegram", error=str(e))
            elapsed = int(now - failed_since)
            log.warning("watchdog: нет связи", elapsed_sec=elapsed)
            if elapsed >= _WATCHDOG_FAIL_TIMEOUT:
                log.error("watchdog: нет связи 10+ мин — завершаю процесс для рестарта")
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
        asyncio.create_task(_watchdog_loop(tg_app))
        await asyncio.Event().wait()
    finally:
        await tg_app.stop()


if __name__ == "__main__":
    asyncio.run(main())
