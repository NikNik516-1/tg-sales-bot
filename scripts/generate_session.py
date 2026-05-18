"""
Запустить ЛОКАЛЬНО (не в Docker) один раз для получения строки сессии.

  pip install pyrogram tgcrypto python-dotenv
  python scripts/generate_session.py

Скопируйте выведенную строку в .env → TG_SESSION_STRING=...
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from pyrogram import Client


async def main():
    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")

    if not api_id or not api_hash:
        print("Заполните TG_API_ID и TG_API_HASH в .env перед запуском.")
        return

    async with Client(":memory:", api_id=int(api_id), api_hash=api_hash, in_memory=True) as app:
        session_string = await app.export_session_string()

    print("\n" + "=" * 70)
    print("Вставьте строку ниже в .env как значение TG_SESSION_STRING=")
    print("=" * 70)
    print(session_string)
    print("=" * 70 + "\n")


asyncio.run(main())
