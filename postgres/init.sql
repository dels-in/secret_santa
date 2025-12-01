-- Инициализация базы данных для Тайного Санты

-- Создание ролей и прав
CREATE ROLE secret_santa_bot WITH LOGIN PASSWORD 'bot_password';
CREATE ROLE secret_santa_admin WITH LOGIN PASSWORD 'admin_password';

-- Предоставление прав
GRANT CONNECT ON DATABASE secret_santa TO secret_santa_bot;
GRANT ALL PRIVILEGES ON DATABASE secret_santa TO secret_santa_admin;

-- Расширения
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Настройки производительности
ALTER DATABASE secret_santa SET search_path TO public;
ALTER DATABASE secret_santa SET timezone TO 'Europe/Moscow';

-- Таблицы будут созданы через SQLAlchemy, но можно добавить дополнительные индексы:
-- CREATE INDEX IF NOT EXISTS idx_users_telegram_gin ON users USING gin(to_tsvector('russian', full_name));
-- CREATE INDEX IF NOT EXISTS idx_groups_name_gin ON groups USING gin(to_tsvector('russian', name));