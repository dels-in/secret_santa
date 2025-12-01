#!/usr/bin/env python3
import sys
import asyncio
import logging
from config import BOT_TOKEN, ADMIN_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_bot():
    print("=== ТЕСТИРОВАНИЕ БОТА ===")

    # 1. Проверка токена
    print(f"1. Проверка токена бота...")
    if not BOT_TOKEN or BOT_TOKEN == "ВАШ_ТОКЕН_ОТ_BOTFATHER":
        print("❌ Токен бота не установлен в .env файле!")
        return False
    print(f"   Токен: {BOT_TOKEN[:10]}... OK")

    # 2. Проверка конфигурации базы данных
    print(f"2. Проверка конфигурации БД...")
    from config import DATABASE_URL
    print(f"   DATABASE_URL: {DATABASE_URL[:30]}...")

    # 3. Проверка импорта модулей
    print(f"3. Проверка импортов...")
    try:
        from database import get_async_db, User
        print("   Модули database... OK")
    except Exception as e:
        print(f"   ❌ Ошибка импорта database: {e}")
        return False

    try:
        from aiogram import Bot, Dispatcher
        print("   Модули aiogram... OK")
    except Exception as e:
        print(f"   ❌ Ошибка импорта aiogram: {e}")
        return False

    # 4. Тест подключения к БД
    print(f"4. Тест подключения к БД...")
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from config import DATABASE_URL

        engine = create_async_engine(DATABASE_URL, echo=False)
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
            print("   Подключение к БД... OK")
    except Exception as e:
        print(f"   ❌ Ошибка подключения к БД: {e}")
        return False

    print("=== ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ ===")
    print("Бот должен работать. Пробуем запустить...")
    return True


if __name__ == "__main__":
    asyncio.run(test_bot())