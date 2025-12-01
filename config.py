import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

# PostgreSQL Configuration
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', '')
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = os.getenv('POSTGRES_PORT', '5432')
POSTGRES_DB = os.getenv('POSTGRES_DB', 'secret_santa')

DATABASE_URL = f'postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}'
SYNC_DATABASE_URL = f'postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}'

# Timezone
TIMEZONE = os.getenv('TIMEZONE', 'Europe/Moscow')

# Security Settings
MAX_REGISTRATIONS_PER_DAY = int(os.getenv('MAX_REGISTRATIONS_PER_DAY', 3))
SPAM_THRESHOLD = int(os.getenv('SPAM_THRESHOLD', 5))
REGISTRATION_COOLDOWN = int(os.getenv('REGISTRATION_COOLDOWN', 300))

# Group Settings
MAX_GROUPS_PER_USER = int(os.getenv('MAX_GROUPS_PER_USER', 5))
DEFAULT_PRICE_LIMIT = os.getenv('DEFAULT_PRICE_LIMIT', "3000 рублей")

# Database Pool
DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', 20))
DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', 40))
DB_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', 3600))