import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, update, delete
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import BOT_TOKEN, ADMIN_ID, TIMEZONE
# Вместо сложных импортов используйте только базовые модели
from database_fixed import get_async_db, User, Event, DrawResult, Group, user_group_association, generate_invite_code


# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize bot
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler(timezone=TIMEZONE)


# States for FSM
class RegistrationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_wishlist = State()
    waiting_for_group_selection = State()


class AdminStates(StatesGroup):
    setting_start_date = State()
    setting_end_date = State()
    sending_broadcast = State()


class MessageStates(StatesGroup):
    waiting_for_anonymous_message = State()


# ==================== HELPER FUNCTIONS ====================

async def get_user(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """Get user by telegram ID"""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def get_active_event(session: AsyncSession, group_id: Optional[int] = None) -> Optional[Event]:
    """Get active event for group"""
    if group_id:
        result = await session.execute(
            select(Event).where(
                Event.group_id == group_id,
                Event.status.in_(['waiting', 'active'])
            ).order_by(Event.created_at.desc())
        )
    else:
        result = await session.execute(
            select(Event).where(Event.status.in_(['waiting', 'active']))
        )
    return result.scalar_one_or_none()


def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id == ADMIN_ID


async def notify_admins(message: str):
    """Send notification to all admins"""
    async with get_async_db() as session:
        result = await session.execute(
            select(User).where(User.is_admin == True)
        )
        admins = result.scalars().all()

        for admin in admins:
            try:
                await bot.send_message(chat_id=admin.telegram_id, text=message)
            except Exception as e:
                logger.error(f"Failed to notify admin {admin.telegram_id}: {e}")


# ==================== USER COMMANDS ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Start command - main menu"""
    async with get_async_db() as session:
        user = await get_user(session, message.from_user.id)

        if user:
            # User already registered
            keyboard = InlineKeyboardBuilder()
            keyboard.button(text="📋 Профиль", callback_data="profile")
            keyboard.button(text="👥 Группы", callback_data="groups")
            keyboard.button(text="🎮 Активная игра", callback_data="active_game")

            if is_admin(message.from_user.id):
                keyboard.button(text="👑 Админ-панель", callback_data="admin_panel")

            keyboard.adjust(2)

            await message.answer(
                f"🎅 Добро пожаловать, {user.full_name}!\n\n"
                f"Выберите действие:",
                reply_markup=keyboard.as_markup()
            )
        else:
            # New user - start registration
            await message.answer(
                "🎅 Добро пожаловать в Тайного Санту!\n\n"
                "Для регистрации мне нужно немного информации.\n"
                "Пожалуйста, напишите ваше ФИО (полное имя):"
            )
            await state.set_state(RegistrationStates.waiting_for_name)


@dp.message(RegistrationStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    """Process user's name"""
    await state.update_data(full_name=message.text)
    await message.answer(
        "Отлично! Теперь напишите ваши пожелания к подарку:\n"
        "(Что вы хотели бы получить? Укажите размеры, цвета, интересы и т.д.)"
    )
    await state.set_state(RegistrationStates.waiting_for_wishlist)


@dp.message(RegistrationStates.waiting_for_wishlist)
async def process_wishlist(message: types.Message, state: FSMContext):
    """Process user's wishlist and complete registration"""
    user_data = await state.get_data()

    async with get_async_db() as session:
        # Check if user already exists
        existing_user = await get_user(session, message.from_user.id)
        if existing_user:
            await message.answer("Вы уже зарегистрированы!")
            await state.clear()
            return

        # Create new user
        new_user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=user_data['full_name'],
            wishlist=message.text,
            is_admin=(message.from_user.id == ADMIN_ID),
            is_global_admin=(message.from_user.id == ADMIN_ID)
        )

        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)

        # Create default group for the user
        default_group = Group(
            name="Моя первая группа",
            description=f"Группа для {new_user.full_name}",
            invite_code=generate_invite_code(),
            creator_id=new_user.id
        )
        session.add(default_group)
        await session.commit()
        await session.refresh(default_group)

        # Add user to the group
        stmt = UserGroupAssociation.insert().values(
            user_id=new_user.id,
            group_id=default_group.id
        )
        await session.execute(stmt)

        # Create default event for the group
        default_event = Event(
            name="Тайный Санта",
            group_id=default_group.id,
            status='waiting'
        )
        session.add(default_event)
        await session.commit()

        await message.answer(
            f"✅ Регистрация успешно завершена!\n\n"
            f"Ваше имя: {user_data['full_name']}\n"
            f"Ваши пожелания сохранены.\n\n"
            f"Создана ваша первая группа:\n"
            f"Название: {default_group.name}\n"
            f"Код приглашения: `{default_group.invite_code}`\n\n"
            f"Используйте /groups для управления группами.",
            parse_mode="Markdown"
        )

        # Notify admin
        await notify_admins(
            f"👤 Новый пользователь зарегистрирован:\n"
            f"• Имя: {new_user.full_name}\n"
            f"• Telegram: @{new_user.username if new_user.username else 'без username'}\n"
            f"• Всего пользователей: {await session.scalar(select(func.count()).select_from(User))}"
        )

    await state.clear()


@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    """Show user profile"""
    async with get_async_db() as session:
        user = await get_user(session, message.from_user.id)

        if not user:
            await message.answer("Вы не зарегистрированы. Используйте /start")
            return

        # Get user's groups
        result = await session.execute(
            select(Group).join(
                UserGroupAssociation, Group.id == UserGroupAssociation.c.group_id
            ).where(UserGroupAssociation.c.user_id == user.id)
        )
        groups = result.scalars().all()

        response = f"👤 **Ваш профиль**\n\n"
        response += f"• Имя: {user.full_name}\n"
        response += f"• Пожелания: {user.wishlist[:100]}...\n"
        response += f"• Групп: {len(groups)}\n"
        response += f"• Дата регистрации: {user.registered_at.strftime('%d.%m.%Y')}\n"

        if is_admin(message.from_user.id):
            response += f"• 👑 Статус: Администратор\n"

        # Check active events
        for group in groups:
            event = await get_active_event(session, group.id)
            if event:
                # Check if user has a draw result
                result = await session.execute(
                    select(DrawResult).where(
                        DrawResult.event_id == event.id,
                        DrawResult.santa_id == user.id
                    )
                )
                draw_result = result.scalar_one_or_none()

                if draw_result:
                    receiver = await session.get(User, draw_result.receiver_id)
                    response += f"\n🎁 **В группе '{group.name}':**\n"
                    response += f"Вы - Тайный Санта для: {receiver.full_name}\n"
                    response += f"Пожелания: {receiver.wishlist[:100]}...\n"

                    keyboard = InlineKeyboardBuilder()
                    keyboard.button(text="✅ Подарок отправлен", callback_data=f"gift_sent_{draw_result.id}")
                    keyboard.button(text="📦 Подарок получен", callback_data=f"gift_delivered_{draw_result.id}")

                    await message.answer(response, reply_markup=keyboard.as_markup(), parse_mode="Markdown")
                    return

        await message.answer(response, parse_mode="Markdown")


# ==================== ADMIN COMMANDS ====================

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Admin panel"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав администратора!")
        return

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📅 Установить даты", callback_data="admin_set_dates")
    keyboard.button(text="👥 Участники", callback_data="admin_view_users")
    keyboard.button(text="🎲 Запустить жеребьевку", callback_data="admin_start_draw")
    keyboard.button(text="📊 Статистика", callback_data="admin_stats")
    keyboard.button(text="📢 Рассылка", callback_data="admin_broadcast")
    keyboard.button(text="🔍 Найти пару", callback_data="admin_find_pair")
    keyboard.adjust(2)

    await message.answer(
        "👑 **Панель администратора**\n\n"
        "Выберите действие:",
        reply_markup=keyboard.as_markup(),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data == "admin_view_users")
async def admin_view_users(callback: types.CallbackQuery):
    """View all registered users"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!")
        return

    async with get_async_db() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()

        response = "👥 **Список участников**\n\n"
        for i, user in enumerate(users, 1):
            response += f"{i}. {user.full_name}"
            if user.username:
                response += f" (@{user.username})"
            response += f"\n   ID: {user.telegram_id}"
            if user.is_banned:
                response += " 🚫"
            response += "\n\n"

        await callback.message.edit_text(
            response,
            parse_mode="Markdown"
        )

    await callback.answer()


@dp.callback_query(F.data == "admin_set_dates")
async def admin_set_dates(callback: types.CallbackQuery, state: FSMContext):
    """Set event dates"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!")
        return

    await callback.message.answer(
        "📅 **Установка дат**\n\n"
        "Введите дату начала игры в формате ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "Пример: 20.12.2024 18:00\n\n"
        "Или отправьте '-' для использования текущей даты."
    )
    await state.set_state(AdminStates.setting_start_date)
    await callback.answer()


@dp.message(AdminStates.setting_start_date)
async def process_start_date(message: types.Message, state: FSMContext):
    """Process start date"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет прав!")
        await state.clear()
        return

    async with get_async_db() as session:
        event = await get_active_event(session)

        if not event:
            await message.answer("❌ Нет активного события. Создайте группу сначала.")
            await state.clear()
            return

        if message.text == '-':
            event.start_date = datetime.now(pytz.timezone(TIMEZONE))
        else:
            try:
                date_obj = datetime.strptime(message.text, '%d.%m.%Y %H:%M')
                date_obj = pytz.timezone(TIMEZONE).localize(date_obj)
                event.start_date = date_obj
            except ValueError:
                await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ ЧЧ:ММ")
                return

        await session.commit()

        await message.answer(
            f"✅ Дата начала установлена: {event.start_date.strftime('%d.%m.%Y %H:%M')}\n\n"
            "Теперь введите дату окончания игры в том же формате:"
        )
        await state.set_state(AdminStates.setting_end_date)


@dp.message(AdminStates.setting_end_date)
async def process_end_date(message: types.Message, state: FSMContext):
    """Process end date"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет прав!")
        await state.clear()
        return

    async with get_async_db() as session:
        event = await get_active_event(session)

        if not event:
            await message.answer("❌ Нет активного события.")
            await state.clear()
            return

        if message.text == '-':
            event.end_date = datetime.now(pytz.timezone(TIMEZONE)) + timedelta(days=7)
        else:
            try:
                date_obj = datetime.strptime(message.text, '%d.%m.%Y %H:%M')
                date_obj = pytz.timezone(TIMEZONE).localize(date_obj)

                if event.start_date and date_obj <= event.start_date:
                    await message.answer("❌ Дата окончания должна быть позже даты начала!")
                    return

                event.end_date = date_obj
            except ValueError:
                await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ ЧЧ:ММ")
                return

        await session.commit()

        # Schedule reminders
        await schedule_reminders(event)

        await message.answer(
            f"✅ Даты установлены успешно!\n\n"
            f"• Начало: {event.start_date.strftime('%d.%m.%Y %H:%M')}\n"
            f"• Окончание: {event.end_date.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Напоминания будут отправлены автоматически."
        )

    await state.clear()


@dp.callback_query(F.data == "admin_start_draw")
async def admin_start_draw(callback: types.CallbackQuery):
    """Start the draw/raffle"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!")
        return

    async with get_async_db() as session:
        event = await get_active_event(session)

        if not event:
            await callback.message.answer("❌ Нет активного события.")
            await callback.answer()
            return

        if not event.start_date or not event.end_date:
            await callback.message.answer("❌ Сначала установите даты начала и окончания.")
            await callback.answer()
            return

        # Get all users from the event's group
        result = await session.execute(
            select(User).join(
                UserGroupAssociation, User.id == UserGroupAssociation.c.user_id
            ).join(
                Group, Group.id == UserGroupAssociation.c.group_id
            ).where(Group.id == event.group_id)
        )
        participants = result.scalars().all()

        if len(participants) < 3:
            await callback.message.answer(f"❌ Недостаточно участников. Нужно минимум 3, а у вас {len(participants)}.")
            await callback.answer()
            return

        # Perform the draw
        success = await perform_draw(session, event, participants)

        if success:
            event.status = 'active'
            await session.commit()

            # Notify participants
            await notify_participants(session, event)

            await callback.message.answer(
                f"✅ Жеребьевка успешно проведена!\n\n"
                f"Участников: {len(participants)}\n"
                f"Все участники уведомлены о своих получателях."
            )
        else:
            await callback.message.answer("❌ Ошибка при проведении жеребьевки.")

    await callback.answer()


async def perform_draw(session: AsyncSession, event: Event, participants: list) -> bool:
    """Perform the secret santa draw"""
    try:
        # Clear previous results
        await session.execute(delete(DrawResult).where(DrawResult.event_id == event.id))

        # Create a copy and shuffle
        receivers = participants.copy()
        random.shuffle(receivers)

        # Ensure no one gets themselves and create a proper chain
        max_attempts = 100
        for attempt in range(max_attempts):
            valid = True
            random.shuffle(receivers)

            for i in range(len(participants)):
                if participants[i].id == receivers[i].id:
                    valid = False
                    break

            if valid:
                break

        if not valid:
            # If still not valid after attempts, adjust manually
            for i in range(len(participants)):
                if participants[i].id == receivers[i].id:
                    # Swap with next participant
                    next_idx = (i + 1) % len(participants)
                    receivers[i], receivers[next_idx] = receivers[next_idx], receivers[i]

        # Create draw results
        for santa, receiver in zip(participants, receivers):
            draw_result = DrawResult(
                event_id=event.id,
                santa_id=santa.id,
                receiver_id=receiver.id
            )
            session.add(draw_result)

        await session.commit()
        return True

    except Exception as e:
        logger.error(f"Error in perform_draw: {e}")
        await session.rollback()
        return False


async def notify_participants(session: AsyncSession, event: Event):
    """Notify all participants about their draw results"""
    result = await session.execute(
        select(DrawResult).where(DrawResult.event_id == event.id)
    )
    draw_results = result.scalars().all()

    for draw in draw_results:
        santa = await session.get(User, draw.santa_id)
        receiver = await session.get(User, draw.receiver_id)

        if santa and receiver:
            message = (
                f"🎅 **Поздравляю, вы - Тайный Санта!**\n\n"
                f"🎁 **Вы дарите подарок:** {receiver.full_name}\n\n"
                f"📝 **Пожелания получателя:**\n{receiver.wishlist}\n\n"
                f"📅 **Срок до:** {event.end_date.strftime('%d.%m.%Y')}\n\n"
                f"🎄 **Советы:**\n"
                f"• Сохраняйте интригу до конца игры\n"
                f"• Подтвердите отправку подарка в профиле\n"
                f"• Не раскрывайте свою личность!"
            )

            try:
                await bot.send_message(
                    chat_id=santa.telegram_id,
                    text=message,
                    parse_mode="Markdown"
                )
                draw.notified = True
            except Exception as e:
                logger.error(f"Failed to notify user {santa.telegram_id}: {e}")

    await session.commit()


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    """Show statistics"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!")
        return

    async with get_async_db() as session:
        # Count users
        total_users = await session.scalar(select(func.count()).select_from(User))
        active_users = await session.scalar(
            select(func.count()).select_from(User).where(
                User.last_activity >= datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=7)
            )
        )

        # Get active event
        event = await get_active_event(session)

        response = "📊 **Статистика**\n\n"
        response += f"• Всего пользователей: {total_users}\n"
        response += f"• Активных (за 7 дней): {active_users}\n"

        if event:
            # Count participants in this event
            result = await session.execute(
                select(func.count()).select_from(DrawResult).where(
                    DrawResult.event_id == event.id
                )
            )
            total_pairs = result.scalar() or 0

            result = await session.execute(
                select(func.count()).select_from(DrawResult).where(
                    DrawResult.event_id == event.id,
                    DrawResult.gift_sent == True
                )
            )
            gifts_sent = result.scalar() or 0

            result = await session.execute(
                select(func.count()).select_from(DrawResult).where(
                    DrawResult.event_id == event.id,
                    DrawResult.gift_delivered == True
                )
            )
            gifts_delivered = result.scalar() or 0

            response += f"\n🎮 **Текущая игра:** {event.name}\n"
            response += f"• Статус: {event.status}\n"
            response += f"• Участников: {total_pairs}\n"
            response += f"• Подарков отправлено: {gifts_sent}/{total_pairs}\n"
            response += f"• Подарков получено: {gifts_delivered}/{total_pairs}\n"

            if event.start_date:
                response += f"• Начало: {event.start_date.strftime('%d.%m.%Y')}\n"
            if event.end_date:
                days_left = (event.end_date - datetime.now(pytz.timezone(TIMEZONE))).days
                response += f"• Окончание через: {days_left} дней\n"

        await callback.message.edit_text(response, parse_mode="Markdown")

    await callback.answer()


# ==================== SCHEDULER FUNCTIONS ====================

async def schedule_reminders(event: Event):
    """Schedule reminder notifications"""
    if not event.start_date or not event.end_date:
        return

    # Remove old jobs for this event
    scheduler.remove_all_jobs()

    # Reminder 1 day before start
    reminder_date = event.start_date - timedelta(days=1)
    if reminder_date > datetime.now(pytz.timezone(TIMEZONE)):
        scheduler.add_job(
            send_reminder,
            CronTrigger(
                year=reminder_date.year,
                month=reminder_date.month,
                day=reminder_date.day,
                hour=12,
                minute=0,
                timezone=TIMEZONE
            ),
            args=[event.id, "start_reminder"]
        )

    # Reminder 1 week before end
    week_reminder = event.end_date - timedelta(days=7)
    if week_reminder > datetime.now(pytz.timezone(TIMEZONE)):
        scheduler.add_job(
            send_reminder,
            CronTrigger(
                year=week_reminder.year,
                month=week_reminder.month,
                day=week_reminder.day,
                hour=12,
                minute=0,
                timezone=TIMEZONE
            ),
            args=[event.id, "week_reminder"]
        )

    # Reminder on the last day
    scheduler.add_job(
        send_reminder,
        CronTrigger(
            year=event.end_date.year,
            month=event.end_date.month,
            day=event.end_date.day,
            hour=10,
            minute=0,
            timezone=TIMEZONE
        ),
        args=[event.id, "final_reminder"]
    )


async def send_reminder(event_id: int, reminder_type: str):
    """Send reminder to all participants"""
    async with get_async_db() as session:
        event = await session.get(Event, event_id)
        if not event:
            return

        # Get all participants in the event's group
        result = await session.execute(
            select(User).join(
                UserGroupAssociation, User.id == UserGroupAssociation.c.user_id
            ).where(UserGroupAssociation.c.group_id == event.group_id)
        )
        participants = result.scalars().all()

        for user in participants:
            try:
                if reminder_type == "start_reminder":
                    message = (
                        f"⏰ **Напоминание!**\n\n"
                        f"Игра 'Тайный Санта' начнется завтра в {event.start_date.strftime('%H:%M')}!\n\n"
                        f"Убедитесь, что вы готовы к жеребьевке!"
                    )
                elif reminder_type == "week_reminder":
                    message = (
                        f"⏰ **Напоминание!**\n\n"
                        f"До окончания игры 'Тайный Санта' осталась неделя!\n\n"
                        f"Успейте отправить подарки до {event.end_date.strftime('%d.%m.%Y')}!"
                    )
                elif reminder_type == "final_reminder":
                    message = (
                        f"⏰ **Последний день игры!**\n\n"
                        f"Сегодня последний день игры 'Тайный Санта'!\n\n"
                        f"Убедитесь, что вы отправили подарки до конца дня!"
                    )
                else:
                    continue

                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=message,
                    parse_mode="Markdown"
                )
                await asyncio.sleep(0.1)  # Rate limiting

            except Exception as e:
                logger.error(f"Failed to send reminder to {user.telegram_id}: {e}")


# ==================== BOT STARTUP ====================

async def on_startup():
    """Actions on bot startup"""
    logger.info("Bot starting up...")

    # Start scheduler
    scheduler.start()

    # TODO: временно отключено - будет добавлено позже
    # Планировщик работает, но без проверки существующих событий

    # # Schedule existing events using new session manager
    # from database import get_db_session
    # async with get_db_session() as session:
    #     result = await session.execute(
    #         select(Event).where(Event.status.in_(['waiting', 'active']))
    #     )
    #     events = result.scalars().all()
    #
    #     for event in events:
    #         if event.start_date and event.end_date:
    #             await schedule_reminders(event)

    # Notify admin
    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text="✅ Бот 'Тайный Санта' запущен и готов к работе!"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")


async def on_shutdown():
    """Actions on bot shutdown"""
    logger.info("Bot shutting down...")
    scheduler.shutdown()


async def main():
    """Main function"""
    # Register startup/shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())