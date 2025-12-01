import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, ADMIN_ID

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize bot
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🎅 Добро пожаловать в Тайного Санту!\n\n"
        "Используйте команды:\n"
        "/register - регистрация в игре\n"
        "/help - помощь\n"
        "/admin - панель управления (только для администратора)"
    )


@dp.message(Command("register"))
async def cmd_register(message: types.Message):
    await message.answer(
        "Для регистрации напишите:\n"
        "1. Ваше ФИО\n"
        "2. Ваши пожелания к подарку\n\n"
        "Пример:\n"
        "Иванов Иван Иванович\n"
        "Хочу книгу по программированию"
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "🎅 Тайный Санта - помощь:\n\n"
        "/start - начать работу с ботом\n"
        "/register - зарегистрироваться в игре\n"
        "/admin - панель администратора\n\n"
        "По вопросам пишите организатору."
    )


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    # ВРЕМЕННО: отладка
    print(f"DEBUG: Ваш ID: {message.from_user.id}, ADMIN_ID из .env: {ADMIN_ID}")
    print(f"DEBUG: Сравнение: {message.from_user.id} == {ADMIN_ID} = {message.from_user.id == ADMIN_ID}")
    # Check if user is admin
    if str(message.from_user.id) == ADMIN_ID:
        await message.answer(
            "👑 Панель администратора\n\n"
            "Вы администратор этого бота!\n"
            "Доступные функции:\n"
            "• Управление участниками\n"
            "• Запуск жеребьевки\n"
            "• Настройка дат\n"
            "• Просмотр статистики"
        )
    else:
        await message.answer("⛔ У вас нет прав администратора!")


@dp.message(F.text)
async def handle_text(message: types.Message):
    # Simple echo for testing
    if message.text.lower() == "привет":
        await message.answer(f"Привет, {message.from_user.first_name}!")


async def main():
    logger.info("Starting bot...")

    # Test bot connection
    try:
        me = await bot.get_me()
        logger.info(f"Bot started: @{me.username}")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        return

    # Start polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())