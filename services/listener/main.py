import asyncio
from pyrogram import Client
from config import TG_API_ID, TG_API_HASH, TG_SESSION_STRING
import chat_manager
import listener
from mq import get_connection, consume, QUEUE_OUTGOING


async def _reload_chats_loop():
    while True:
        await asyncio.sleep(60)
        try:
            await chat_manager.reload()
        except Exception as e:
            print(f"[CHATS] Ошибка reload: {e}")


async def main():
    print("[BOOT] Загрузка списка групп...")
    await chat_manager.load()

    print("[BOOT] Подключение к RabbitMQ...")
    mq_conn = await get_connection()
    listener.set_mq_connection(mq_conn)

    print("[BOOT] Подключение к Telegram...")
    tg_app = Client(
        "seller",
        api_id=TG_API_ID,
        api_hash=TG_API_HASH,
        session_string=TG_SESSION_STRING,
    )
    listener.register(tg_app)

    async with tg_app:
        me = await tg_app.get_me()
        print(f"[BOOT] Запущен как @{me.username} (id={me.id})")
        print("[BOOT] Слушаю сообщения...")

        asyncio.create_task(_reload_chats_loop())

        async def outgoing_handler(payload: dict) -> None:
            await listener.handle_outgoing(tg_app, payload)

        await consume(mq_conn, QUEUE_OUTGOING, outgoing_handler)


if __name__ == "__main__":
    asyncio.run(main())
