from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Table, \
    UniqueConstraint, BigInteger, Numeric, Index, CheckConstraint
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, AsyncEngine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.pool import NullPool
from datetime import datetime, timedelta
import pytz
import secrets
import string
from typing import AsyncGenerator

from config import DATABASE_URL, SYNC_DATABASE_URL, TIMEZONE, DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_RECYCLE, \
    DB_SSL_MODE

# Создаем async engine для асинхронной работы
async_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_recycle=DB_POOL_RECYCLE,
    pool_pre_ping=True,
    connect_args={
        "server_settings": {
            "application_name": "secret_santa_bot"
        }
    }
)

# Создаем sync engine для миграций и синхронных операций
sync_engine = create_engine(
    SYNC_DATABASE_URL,
    echo=False,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_recycle=DB_POOL_RECYCLE,
    pool_pre_ping=True
)

AsyncSessionLocal = sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

SyncSessionLocal = sessionmaker(
    sync_engine,
    expire_on_commit=False
)

Base = declarative_base()


# Таблица для связи многие-ко-многим: пользователи и группы
class UserGroupAssociation(Base):
    __tablename__ = 'user_group_association'

    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='CASCADE'), primary_key=True)
    joined_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    # Индексы для быстрого поиска
    __table_args__ = (
        UniqueConstraint('user_id', 'group_id', name='unique_user_group'),
        Index('idx_user_group_user', 'user_id'),
        Index('idx_user_group_group', 'group_id'),
    )


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)  # BIGINT для больших ID
    username = Column(String(64), nullable=True)
    full_name = Column(String(200), nullable=False)
    wishlist = Column(Text, nullable=False)
    contact_info = Column(Text, nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_global_admin = Column(Boolean, default=False, nullable=False)
    is_banned = Column(Boolean, default=False, nullable=False)
    spam_score = Column(Integer, default=0, nullable=False)
    last_activity = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))
    registered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    # Связи
    groups = relationship("Group", secondary="user_group_association", back_populates="members")
    created_groups = relationship("Group", back_populates="creator")
    as_santa = relationship('DrawResult', foreign_keys='DrawResult.santa_id', back_populates='santa',
                            cascade="all, delete-orphan")
    as_receiver = relationship('DrawResult', foreign_keys='DrawResult.receiver_id', back_populates='receiver',
                               cascade="all, delete-orphan")
    sent_messages = relationship('AnonymousMessage', foreign_keys='AnonymousMessage.sender_id', back_populates='sender',
                                 cascade="all, delete-orphan")
    received_messages = relationship('AnonymousMessage', foreign_keys='AnonymousMessage.receiver_id',
                                     back_populates='receiver', cascade="all, delete-orphan")
    feedbacks_given = relationship('Feedback', foreign_keys='Feedback.giver_id', back_populates='giver',
                                   cascade="all, delete-orphan")
    feedbacks_received = relationship('Feedback', foreign_keys='Feedback.receiver_id', back_populates='receiver',
                                      cascade="all, delete-orphan")
    created_invites = relationship('InviteCode', back_populates='creator', cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_users_telegram', 'telegram_id'),
        Index('idx_users_username', 'username'),
        Index('idx_users_activity', 'last_activity'),
        CheckConstraint('spam_score >= 0', name='spam_score_non_negative'),
    )


class Group(Base):
    __tablename__ = 'groups'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    invite_code = Column(String(10), unique=True, index=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_public = Column(Boolean, default=False, nullable=False)
    max_participants = Column(Integer, default=100, nullable=False)
    registration_open = Column(Boolean, default=True, nullable=False)
    creator_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    # Связи
    creator = relationship("User", back_populates="created_groups")
    members = relationship("User", secondary="user_group_association", back_populates="groups")
    events = relationship("Event", back_populates="group", cascade="all, delete-orphan")
    invites = relationship('InviteCode', back_populates='group', cascade="all, delete-orphan")
    anonymous_messages = relationship('AnonymousMessage', back_populates='group', cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_groups_invite_code', 'invite_code'),
        Index('idx_groups_creator', 'creator_id'),
        Index('idx_groups_created', 'created_at'),
        CheckConstraint('max_participants > 0', name='positive_max_participants'),
    )


class Event(Base):
    __tablename__ = 'events'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='CASCADE'), nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default='waiting', nullable=False)  # waiting, active, finished, cancelled
    price_limit = Column(String(100), nullable=True)
    draw_method = Column(String(20), default='auto', nullable=False)  # auto, manual, hybrid
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    # Связи
    group = relationship("Group", back_populates="events")
    results = relationship('DrawResult', back_populates='event', cascade="all, delete-orphan")
    feedbacks = relationship('Feedback', back_populates='event', cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_events_group', 'group_id'),
        Index('idx_events_status', 'status'),
        Index('idx_events_dates', 'start_date', 'end_date'),
        CheckConstraint("status IN ('waiting', 'active', 'finished', 'cancelled')", name='valid_status'),
    )


class DrawResult(Base):
    __tablename__ = 'draw_results'

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    santa_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    receiver_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    gift_sent = Column(Boolean, default=False, nullable=False)
    gift_delivered = Column(Boolean, default=False, nullable=False)
    gift_confirmed = Column(Boolean, default=False, nullable=False)
    notified = Column(Boolean, default=False, nullable=False)
    manual_assignment = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    # Связи
    event = relationship('Event', back_populates='results')
    santa = relationship('User', foreign_keys=[santa_id], back_populates='as_santa')
    receiver = relationship('User', foreign_keys=[receiver_id], back_populates='as_receiver')

    __table_args__ = (
        UniqueConstraint('event_id', 'santa_id', name='unique_event_santa'),
        UniqueConstraint('event_id', 'receiver_id', name='unique_event_receiver'),
        Index('idx_draw_event', 'event_id'),
        Index('idx_draw_santa', 'santa_id'),
        Index('idx_draw_receiver', 'receiver_id'),
        Index('idx_draw_status', 'gift_sent', 'gift_delivered'),
        CheckConstraint('santa_id != receiver_id', name='no_self_gift'),
    )


class AnonymousMessage(Base):
    __tablename__ = 'anonymous_messages'

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    receiver_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='CASCADE'), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    # Связи
    sender = relationship('User', foreign_keys=[sender_id], back_populates='sent_messages')
    receiver = relationship('User', foreign_keys=[receiver_id], back_populates='received_messages')
    group = relationship("Group", back_populates="anonymous_messages")

    __table_args__ = (
        Index('idx_messages_receiver', 'receiver_id'),
        Index('idx_messages_sender', 'sender_id'),
        Index('idx_messages_group', 'group_id'),
        Index('idx_messages_created', 'created_at'),
    )


class Feedback(Base):
    __tablename__ = 'feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    giver_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    receiver_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    is_anonymous = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    # Связи
    event = relationship('Event', back_populates='feedbacks')
    giver = relationship('User', foreign_keys=[giver_id], back_populates='feedbacks_given')
    receiver = relationship('User', foreign_keys=[receiver_id], back_populates='feedbacks_received')

    __table_args__ = (
        UniqueConstraint('event_id', 'giver_id', 'receiver_id', name='unique_feedback'),
        Index('idx_feedback_event', 'event_id'),
        Index('idx_feedback_giver', 'giver_id'),
        Index('idx_feedback_receiver', 'receiver_id'),
        CheckConstraint('rating >= 1 AND rating <= 5', name='rating_range'),
    )


class InviteCode(Base):
    __tablename__ = 'invite_codes'

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), unique=True, index=True, nullable=False)
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='CASCADE'), nullable=False)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    max_uses = Column(Integer, default=1, nullable=False)
    used_count = Column(Integer, default=0, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    # Связи
    group = relationship("Group", back_populates="invites")
    creator = relationship("User", back_populates="created_invites")

    __table_args__ = (
        Index('idx_invites_code', 'code'),
        Index('idx_invites_group', 'group_id'),
        Index('idx_invites_expires', 'expires_at'),
        Index('idx_invites_active', 'is_active'),
        CheckConstraint('max_uses > 0', name='positive_max_uses'),
        CheckConstraint('used_count >= 0', name='non_negative_used_count'),
        CheckConstraint('used_count <= max_uses', name='used_within_limit'),
    )


class AdminNotification(Base):
    __tablename__ = 'admin_notifications'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='CASCADE'), nullable=False)
    message = Column(Text, nullable=False)
    is_resolved = Column(Boolean, default=False, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    # Связи
    user = relationship("User", foreign_keys=[user_id])
    group = relationship("Group")
    resolver = relationship("User", foreign_keys=[resolved_by])

    __table_args__ = (
        Index('idx_notifications_user', 'user_id'),
        Index('idx_notifications_group', 'group_id'),
        Index('idx_notifications_resolved', 'is_resolved'),
        Index('idx_notifications_created', 'created_at'),
    )


class ExclusionRule(Base):
    __tablename__ = 'exclusion_rules'

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    user1_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    user2_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    rule_type = Column(String(20), default='mutual', nullable=False)  # mutual, directional
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    # Связи
    event = relationship("Event")
    user1 = relationship("User", foreign_keys=[user1_id])
    user2 = relationship("User", foreign_keys=[user2_id])

    __table_args__ = (
        UniqueConstraint('event_id', 'user1_id', 'user2_id', name='unique_exclusion'),
        Index('idx_exclusions_event', 'event_id'),
        Index('idx_exclusions_users', 'user1_id', 'user2_id'),
        CheckConstraint("rule_type IN ('mutual', 'directional')", name='valid_rule_type'),
        CheckConstraint('user1_id != user2_id', name='different_users'),
    )


class ActivityLog(Base):
    __tablename__ = 'activity_logs'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    action = Column(String(50), nullable=False)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)  # Поддержка IPv6
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    # Связи
    user = relationship("User")

    __table_args__ = (
        Index('idx_logs_user', 'user_id'),
        Index('idx_logs_action', 'action'),
        Index('idx_logs_created', 'created_at'),
    )


# Асинхронные функции для работы с БД
async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_sync_db():
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


def generate_invite_code(length=8) -> str:
    """Генерация уникального кода приглашения"""
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(length))
        db = SyncSessionLocal()
        existing = db.query(InviteCode).filter(InviteCode.code == code).first()
        db.close()
        if not existing:
            return code


# Функция создания таблиц (для миграций)
def create_tables():
    Base.metadata.create_all(bind=sync_engine)


# Функция удаления таблиц (для тестов)
def drop_tables():
    Base.metadata.drop_all(bind=sync_engine)