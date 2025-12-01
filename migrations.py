#!/usr/bin/env python3
"""
Скрипт миграций базы данных для PostgreSQL
"""
import sys
import asyncio
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database import sync_engine, Base, get_sync_db
from config import SYNC_DATABASE_URL


def init_database():
    print("🔄 Инициализация базы данных PostgreSQL...")

    try:
        # Создаем таблицы
        Base.metadata.create_all(bind=sync_engine)
        print("✅ Таблицы успешно созданы")

        # Создаем расширения PostgreSQL если нужно
        with sync_engine.begin() as conn:  # ИЗМЕНИЛИ connect() на begin()
        # Включаем расширение для UUID если планируете использовать
        # conn.execute(text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";"))

        # Создаем индексы для полнотекстового поиска если нужно
        conn.execute(text("CREATE INDEX idx_users_full_name_gin ON users USING gin(to_tsvector('russian', full_name));"))

        # НЕ НУЖНО вызывать conn.commit() - begin() делает это автоматически

        print("✅ База данных успешно инициализирована")
        return True

    except SQLAlchemyError as e:
        print(f"❌ Ошибка при инициализации БД: {e}")
        return False


def create_partitions():
    """Создание партиций для больших таблиц (опционально)"""
    print("🔄 Создание партиций для больших таблиц...")

    try:
        with sync_engine.begin() as conn:  # ИЗМЕНИТЕ connect() на begin()
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS activity_logs_2024_01 PARTITION OF activity_logs
                FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
            """))

            # НЕ НУЖНО conn.commit()

        print("✅ Партиции созданы")
        return True

    except Exception as e:
        print(f"⚠️ Не удалось создать партиции: {e}")
        return True  # Не критичная ошибка


def run_migrations():
    """Запуск всех миграций"""
    print("🚀 Запуск миграций базы данных...")

    # 1. Инициализация БД
    if not init_database():
        return False

    # 2. Создание партиций - временно отключено
    ## create_partitions()

    # 3. Добавление тестовых данных (опционально)
    if len(sys.argv) > 1 and sys.argv[1] == "--test-data":
        from seed import seed_test_data
        seed_test_data()

    print("🎉 Все миграции успешно выполнены!")
    return True


if __name__ == "__main__":
    success = run_migrations()
    sys.exit(0 if success else 1)