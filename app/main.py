import asyncio
import uvicorn
from pyrogram import Client
from config import TG_API_ID, TG_API_HASH, TG_SESSION_STRING
import rag
import listener
import chat_manager
from admin_server import app as admin_app


async def main():
    print("[BOOT] Инициализация RAG...")
    rag.init()

    print("[BOOT] Загрузка списка групп...")
    await chat_manager.load()

    print("[BOOT] Подключение к Telegram...")
    tg_app = Client(
        "seller",
        api_id=TG_API_ID,
        api_hash=TG_API_HASH,
        session_string=TG_SESSION_STRING,
    )

    listener.register(tg_app)

    config = uvicorn.Config(admin_app, host="0.0.0.0", port=8080, log_level="warning")
    server = uvicorn.Server(config)

    async with tg_app:
        me = await tg_app.get_me()
        print(f"[BOOT] Запущен как @{me.username} (id={me.id})")
        print("[BOOT] Слушаю сообщения...")
        print("[BOOT] Админка: http://localhost:8080")
        await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
