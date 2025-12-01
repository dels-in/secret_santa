#!/usr/bin/env python3
"""
Database migration script for PostgreSQL
"""
import sys
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database import sync_engine, Base


def init_database():
    """Initialize database and create tables"""
    print("🔄 Инициализация базы данных PostgreSQL...")

    try:
        # Create tables
        Base.metadata.create_all(bind=sync_engine)
        print("✅ Таблицы успешно созданы")

        # Create PostgreSQL extensions if needed
        with sync_engine.begin() as conn:
            # Enable UUID extension if you plan to use it
            # conn.execute(text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";"))
            pass

        print("✅ База данных успешно инициализирована")
        return True

    except SQLAlchemyError as e:
        print(f"❌ Ошибка при инициализации БД: {e}")
        return False


def run_migrations():
    """Run all migrations"""
    print("🚀 Запуск миграций базы данных...")

    # 1. Initialize database
    if not init_database():
        return False

    print("🎉 Все миграции успешно выполнены!")
    return True


if __name__ == "__main__":
    success = run_migrations()
    sys.exit(0 if success else 1)