# Изменения в импортах
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, or_, func
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy import text
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import BOT_TOKEN, ADMIN_ID, TIMEZONE
from database import get_async_db, User, Group, Event, DrawResult, AnonymousMessage, Feedback, InviteCode, \
    AdminNotification, ExclusionRule, ActivityLog, UserGroupAssociation

# Пример асинхронных запросов к PostgreSQL
async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """Асинхронное получение пользователя по Telegram ID"""
    result = await session.execute(
        select(User)
        .where(User.telegram_id == telegram_id)
        .options(selectinload(User.groups))
    )
    return result.scalar_one_or_none()


async def get_group_with_members(session: AsyncSession, group_id: int) -> Optional[Group]:
    """Асинхронное получение группы с участниками"""
    result = await session.execute(
        select(Group)
        .where(Group.id == group_id)
        .options(
            selectinload(Group.members),
            selectinload(Group.creator),
            selectinload(Group.events)
        )
    )
    return result.scalar_one_or_none()


async def create_new_user(session: AsyncSession, user_data: Dict[str, Any]) -> User:
    """Асинхронное создание нового пользователя"""
    new_user = User(
        telegram_id=user_data['telegram_id'],
        username=user_data.get('username'),
        full_name=user_data['full_name'],
        wishlist=user_data['wishlist'],
        is_admin=(str(user_data['telegram_id']) == ADMIN_ID)
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    return new_user


async def perform_draw_async(session: AsyncSession, event: Event) -> bool:
    """Асинхронная жеребьевка с использованием PostgreSQL функций"""
    try:
        # Получаем всех участников группы
        group = await session.get(Group, event.group_id, options=[selectinload(Group.members)])

        if not group or len(group.members) < 3:
            return False

        participants = group.members

        # Удаляем старые результаты
        await session.execute(
            delete(DrawResult).where(DrawResult.event_id == event.id)
        )

        # Получаем правила исключений
        exclusions_result = await session.execute(
            select(ExclusionRule).where(ExclusionRule.event_id == event.id)
        )
        exclusions = exclusions_result.scalars().all()

        # Создаем список для распределения
        receivers = participants.copy()
        import random
        random.shuffle(receivers)

        # Создаем пары с учетом исключений
        pairs = []
        max_attempts = 100

        for attempt in range(max_attempts):
            random.shuffle(receivers)
            valid = True
            pairs = []

            for i, santa in enumerate(participants):
                receiver = receivers[i]

                # Проверка исключений
                if any(
                        (excl.user1_id == santa.id and excl.user2_id == receiver.id) or
                        (excl.rule_type == 'mutual' and excl.user2_id == santa.id and excl.user1_id == receiver.id)
                        for excl in exclusions
                ):
                    valid = False
                    break

                # Проверка на самоподарок
                if santa.id == receiver.id:
                    valid = False
                    break

                pairs.append((santa.id, receiver.id))

            if valid:
                break

        if not valid:
            return False

        # Сохраняем результаты в БД
        for santa_id, receiver_id in pairs:
            draw_result = DrawResult(
                event_id=event.id,
                santa_id=santa_id,
                receiver_id=receiver_id
            )
            session.add(draw_result)

        await session.commit()
        return True

    except Exception as e:
        logging.error(f"Error in perform_draw_async: {e}")
        await session.rollback()
        return False

# ... остальной код адаптировать аналогичным образом ...