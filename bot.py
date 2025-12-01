import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Optional, List

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, and_, or_
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import BOT_TOKEN, ADMIN_ID, TIMEZONE
from database import get_db_session, User, Event, DrawResult, Group, user_group_association
from database import generate_invite_code, InviteCode, ExclusionRule

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize bot
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler(timezone=TIMEZONE)


# ==================== STATES ====================

class RegistrationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_wishlist = State()


class GroupStates(StatesGroup):
    creating_group_name = State()
    creating_group_description = State()
    joining_group = State()
    managing_group = State()


class AdminStates(StatesGroup):
    setting_start_date = State()
    setting_end_date = State()
    sending_broadcast = State()
    manual_pair_selection = State()


class UserStates(StatesGroup):
    editing_profile = State()
    editing_wishlist = State()


# ==================== HELPER FUNCTIONS ====================

async def get_user(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """Get user by telegram ID"""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def get_group(session: AsyncSession, group_id: int) -> Optional[Group]:
    """Get group by ID"""
    result = await session.execute(
        select(Group).where(Group.id == group_id)
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


async def user_in_group(session: AsyncSession, user_id: int, group_id: int) -> bool:
    """Check if user is in group"""
    result = await session.execute(
        select(user_group_association).where(
            user_group_association.c.user_id == user_id,
            user_group_association.c.group_id == group_id
        )
    )
    return result.first() is not None


async def get_user_groups(session: AsyncSession, user_id: int) -> List[Group]:
    """Get all groups where user is a member"""
    result = await session.execute(
        select(Group).join(
            user_group_association, Group.id == user_group_association.c.group_id
        ).where(user_group_association.c.user_id == user_id)
    )
    return result.scalars().all()


# ==================== USER COMMANDS ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Start command - registration or main menu"""
    async with get_db_session() as session:
        user = await get_user(session, message.from_user.id)

        if user:
            # User already registered - show main menu
            keyboard = InlineKeyboardBuilder()
            keyboard.button(text="📋 Мой профиль", callback_data="profile")
            keyboard.button(text="👥 Мои группы", callback_data="my_groups")
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

    async with get_db_session() as session:
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

        await message.answer(
            f"✅ Регистрация успешно завершена!\n\n"
            f"Ваше имя: {user_data['full_name']}\n"
            f"Ваши пожелания сохранены.\n\n"
            f"Теперь создайте свою первую группу или присоединитесь к существующей."
        )

    await state.clear()

    # Show group creation options
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="📦 Создать группу", callback_data="create_group_init")
    keyboard.button(text="🔗 Присоединиться к группе", callback_data="join_group_init")
    await message.answer("Выберите действие:", reply_markup=keyboard.as_markup())


@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    """Show user profile with edit options"""
    async with get_db_session() as session:
        user = await get_user(session, message.from_user.id)

        if not user:
            await message.answer("Вы не зарегистрированы. Используйте /start")
            return

        # Get user's groups
        groups = await get_user_groups(session, user.id)

        response = f"👤 **Ваш профиль**\n\n"
        response += f"• Имя: {user.full_name}\n"
        response += f"• Пожелания: {user.wishlist[:100]}...\n"
        response += f"• Групп: {len(groups)}\n"
        response += f"• Дата регистрации: {user.registered_at.strftime('%d.%m.%Y')}\n"

        if is_admin(message.from_user.id):
            response += f"• 👑 Статус: Администратор\n"

        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="✏️ Изменить ФИО", callback_data="edit_name")
        keyboard.button(text="🎁 Изменить пожелания", callback_data="edit_wishlist")
        keyboard.button(text="📱 Добавить контакты", callback_data="add_contacts")
        keyboard.adjust(2)

        await message.answer(response, reply_markup=keyboard.as_markup(), parse_mode="Markdown")


# ==================== GROUP MANAGEMENT ====================

@dp.callback_query(F.data == "create_group_init")
async def create_group_init(callback: types.CallbackQuery, state: FSMContext):
    """Start group creation process"""
    await callback.message.answer(
        "📦 **Создание новой группы**\n\n"
        "Введите название для группы (максимум 100 символов):",
        parse_mode="Markdown"
    )
    await state.set_state(GroupStates.creating_group_name)
    await callback.answer()


@dp.message(GroupStates.creating_group_name)
async def process_group_name(message: types.Message, state: FSMContext):
    """Process group name"""
    if len(message.text) > 100:
        await message.answer("❌ Слишком длинное название. Максимум 100 символов.")
        return

    await state.update_data(group_name=message.text)
    await message.answer(
        "📝 Введите описание группы (необязательно, можно пропустить, отправив '-'):"
    )
    await state.set_state(GroupStates.creating_group_description)


@dp.message(GroupStates.creating_group_description)
async def process_group_description(message: types.Message, state: FSMContext):
    """Process group description and create group"""
    user_data = await state.get_data()
    description = None if message.text == '-' else message.text

    async with get_db_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await message.answer("❌ Ошибка: пользователь не найден")
            await state.clear()
            return

        # Check group limit
        user_groups = await get_user_groups(session, user.id)
        if len(user_groups) >= 5:  # Limit to 5 groups per user
            await message.answer("❌ Вы достигли лимита групп (5 групп на пользователя)")
            await state.clear()
            return

        # Create group
        new_group = Group(
            name=user_data['group_name'],
            description=description,
            invite_code=generate_invite_code(),
            creator_id=user.id
        )
        session.add(new_group)
        await session.commit()
        await session.refresh(new_group)

        # Add creator to group
        stmt = user_group_association.insert().values(
            user_id=user.id,
            group_id=new_group.id
        )
        await session.execute(stmt)

        # Create default event for the group
        default_event = Event(
            name="Тайный Санта",
            group_id=new_group.id,
            status='waiting'
        )
        session.add(default_event)
        await session.commit()

        # Create invite code
        invite = InviteCode(
            code=new_group.invite_code,
            group_id=new_group.id,
            created_by=user.id,
            max_uses=50,
            expires_at=datetime.now(pytz.timezone(TIMEZONE)) + timedelta(days=30)
        )
        session.add(invite)
        await session.commit()

        await message.answer(
            f"✅ Группа *{new_group.name}* создана!\n\n"
            f"📋 **Информация:**\n"
            f"• Код приглашения: `{new_group.invite_code}`\n"
            f"• Участников: 1\n"
            f"• Статус: Открыта для регистрации\n\n"
            f"📢 **Пригласите друзей:**\n"
            f"Отправьте им код: `{new_group.invite_code}`\n"
            f"Или используйте команду:\n"
            f"`/join {new_group.invite_code}`",
            parse_mode="Markdown"
        )

    await state.clear()


@dp.callback_query(F.data == "join_group_init")
async def join_group_init(callback: types.CallbackQuery, state: FSMContext):
    """Start group joining process"""
    await callback.message.answer(
        "🔗 **Присоединение к группе**\n\n"
        "Введите код приглашения:",
        parse_mode="Markdown"
    )
    await state.set_state(GroupStates.joining_group)
    await callback.answer()


@dp.message(GroupStates.joining_group)
async def process_join_group(message: types.Message, state: FSMContext):
    """Process group joining"""
    invite_code = message.text.upper().strip()

    async with get_db_session() as session:
        # Find group by invite code
        result = await session.execute(
            select(Group).where(Group.invite_code == invite_code)
        )
        group = result.scalar_one_or_none()

        if not group:
            await message.answer("❌ Группа с таким кодом не найдена")
            await state.clear()
            return

        if not group.registration_open:
            await message.answer("❌ Регистрация в этой группе закрыта")
            await state.clear()
            return

        # Check if user is already in group
        user = await get_user(session, message.from_user.id)
        if not user:
            await message.answer("❌ Сначала зарегистрируйтесь через /start")
            await state.clear()
            return

        if await user_in_group(session, user.id, group.id):
            await message.answer("❌ Вы уже состоите в этой группе")
            await state.clear()
            return

        # Check group capacity
        result = await session.execute(
            select(func.count()).select_from(
                user_group_association
            ).where(user_group_association.c.group_id == group.id)
        )
        member_count = result.scalar()

        if member_count >= group.max_participants:
            await message.answer("❌ Группа заполнена")
            await state.clear()
            return

        # Add user to group
        stmt = user_group_association.insert().values(
            user_id=user.id,
            group_id=group.id
        )
        await session.execute(stmt)

        # Update invite code usage
        result = await session.execute(
            select(InviteCode).where(InviteCode.code == invite_code)
        )
        invite = result.scalar_one_or_none()
        if invite:
            invite.used_count += 1
            if invite.used_count >= invite.max_uses:
                invite.is_active = False

        await session.commit()

        await message.answer(
            f"✅ Вы присоединились к группе *{group.name}*!\n\n"
            f"📋 **Информация:**\n"
            f"• Участников: {member_count + 1}\n"
            f"• Организатор: {group.creator.full_name}\n"
            f"• Описание: {group.description if group.description else 'нет'}\n\n"
            f"Используйте /my_groups для просмотра ваших групп.",
            parse_mode="Markdown"
        )

    await state.clear()


@dp.message(Command("join"))
async def cmd_join(message: types.Message):
    """Join group via command with invite code"""
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: `/join КОД_ПРИГЛАШЕНИЯ`", parse_mode="Markdown")
        return

    invite_code = args[1].upper().strip()
    await process_join_group(message, None)  # Используем ту же функцию


@dp.message(Command("my_groups"))
async def cmd_my_groups(message: types.Message):
    """Show user's groups"""
    async with get_db_session() as session:
        user = await get_user(session, message.from_user.id)

        if not user:
            await message.answer("Сначала зарегистрируйтесь через /start")
            return

        groups = await get_user_groups(session, user.id)

        if not groups:
            await message.answer(
                "📋 **У вас пока нет групп**\n\n"
                "Создайте свою группу или присоединитесь к существующей:\n"
                "• /create_group - создать новую группу\n"
                "• /join КОД - присоединиться по коду",
                parse_mode="Markdown"
            )
            return

        response = "📋 **Ваши группы:**\n\n"
        keyboard = InlineKeyboardBuilder()

        for group in groups:
            # Count members
            result = await session.execute(
                select(func.count()).select_from(
                    user_group_association
                ).where(user_group_association.c.group_id == group.id)
            )
            member_count = result.scalar()

            # Get active event
            event = await get_active_event(session, group.id)

            response += f"🎮 *{group.name}*\n"
            response += f"   👥 Участников: {member_count}\n"
            response += f"   🔑 Код: `{group.invite_code}`\n"
            if event:
                status_emoji = "🟢" if event.status == 'active' else "🟡"
                response += f"   {status_emoji} Статус: {event.status}\n"
            response += "\n"

            # Add button for group management
            keyboard.button(text=f"👥 {group.name}", callback_data=f"group_{group.id}")

        keyboard.button(text="📦 Создать группу", callback_data="create_group_init")
        keyboard.button(text="🔗 Присоединиться", callback_data="join_group_init")
        keyboard.adjust(1)

        await message.answer(response, reply_markup=keyboard.as_markup(), parse_mode="Markdown")


@dp.callback_query(F.data.startswith("group_"))
async def group_detail(callback: types.CallbackQuery):
    """Show group details"""
    group_id = int(callback.data.split("_")[1])

    async with get_db_session() as session:
        group = await get_group(session, group_id)
        if not group:
            await callback.answer("❌ Группа не найдена")
            return

        # Check if user is in group
        user = await get_user(session, callback.from_user.id)
        if not user or not await user_in_group(session, user.id, group.id):
            await callback.answer("❌ Вы не состоите в этой группе")
            return

        # Count members
        result = await session.execute(
            select(func.count()).select_from(
                user_group_association
            ).where(user_group_association.c.group_id == group.id)
        )
        member_count = result.scalar()

        # Get active event
        event = await get_active_event(session, group.id)

        response = f"🎮 **Группа: {group.name}**\n\n"
        response += f"📝 Описание: {group.description if group.description else 'нет'}\n"
        response += f"👥 Участников: {member_count}\n"
        response += f"🔑 Код приглашения: `{group.invite_code}`\n"
        response += f"👑 Создатель: {group.creator.full_name}\n\n"

        if event:
            response += f"🎅 **Активное событие:** {event.name}\n"
            response += f"📅 Статус: {event.status}\n"
            if event.start_date:
                response += f"⏰ Начало: {event.start_date.strftime('%d.%m.%Y %H:%M')}\n"
            if event.end_date:
                response += f"🏁 Окончание: {event.end_date.strftime('%d.%m.%Y %H:%M')}\n"

        keyboard = InlineKeyboardBuilder()

        # Different buttons for admin and regular members
        if group.creator_id == user.id or user.is_global_admin:
            keyboard.button(text="⚙️ Управление группой", callback_data=f"manage_group_{group.id}")
            keyboard.button(text="👥 Участники", callback_data=f"group_members_{group.id}")
            keyboard.button(text="🎲 Запустить жеребьевку", callback_data=f"start_draw_{group.id}")
            keyboard.button(text="📅 Установить даты", callback_data=f"set_dates_{group.id}")
        else:
            keyboard.button(text="👥 Участники", callback_data=f"group_members_{group.id}")
            keyboard.button(text="📊 Статистика", callback_data=f"group_stats_{group.id}")

        keyboard.button(text="◀️ Назад к группам", callback_data="back_to_groups")
        keyboard.adjust(2)

        await callback.message.edit_text(
            response,
            reply_markup=keyboard.as_markup(),
            parse_mode="Markdown"
        )

    await callback.answer()


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
    keyboard.button(text="📦 Группы", callback_data="admin_groups")
    keyboard.adjust(2)

    await message.answer(
        "👑 **Панель администратора**\n\n"
        "Выберите действие:",
        reply_markup=keyboard.as_markup(),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data == "admin_groups")
async def admin_groups_list(callback: types.CallbackQuery):
    """Show all groups for admin"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!")
        return

    async with get_db_session() as session:
        result = await session.execute(select(Group))
        groups = result.scalars().all()

        if not groups:
            await callback.message.answer("❌ Нет созданных групп")
            await callback.answer()
            return

        response = "📦 **Все группы:**\n\n"

        for group in groups:
            # Count members
            result = await session.execute(
                select(func.count()).select_from(
                    user_group_association
                ).where(user_group_association.c.group_id == group.id)
            )
            member_count = result.scalar()

            response += f"🎮 *{group.name}*\n"
            response += f"   👥 Участников: {member_count}\n"
            response += f"   🔑 Код: `{group.invite_code}`\n"
            response += f"   👑 Создатель: {group.creator.full_name}\n\n"

        await callback.message.edit_text(response, parse_mode="Markdown")

    await callback.answer()


# ==================== SCHEDULER FUNCTIONS ====================

async def schedule_reminders(event: Event):
    """Schedule reminder notifications for event"""
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
    async with get_db_session() as session:
        event = await session.get(Event, event_id)
        if not event:
            return

        # Get all participants in the event's group
        result = await session.execute(
            select(User).join(
                user_group_association, User.id == user_group_association.c.user_id
            ).where(user_group_association.c.group_id == event.group_id)
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