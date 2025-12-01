from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Table, UniqueConstraint, \
    BigInteger, Index, CheckConstraint
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy import text
from datetime import datetime
import pytz
import secrets
import string
from typing import AsyncGenerator

from config import DATABASE_URL, SYNC_DATABASE_URL, TIMEZONE

from contextlib import asynccontextmanager

@asynccontextmanager
async def get_db_session():
    """Async context manager for database sessions"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# Async engine for main application
async_engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine for migrations
from sqlalchemy import create_engine

sync_engine = create_engine(SYNC_DATABASE_URL, echo=False)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False)

Base = declarative_base()

# Association table for many-to-many relationship
user_group_association = Table(
    'user_group_association',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('group_id', Integer, ForeignKey('groups.id', ondelete='CASCADE'), primary_key=True),
    Column('joined_at', DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE))),
    Index('idx_user_group_user', 'user_id'),
    Index('idx_user_group_group', 'group_id'),
)


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
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

    # Relationships
    groups = relationship("Group", secondary=user_group_association, back_populates="members")
    created_groups = relationship("Group", back_populates="creator")
    as_santa = relationship('DrawResult', foreign_keys='DrawResult.santa_id', back_populates='santa')
    as_receiver = relationship('DrawResult', foreign_keys='DrawResult.receiver_id', back_populates='receiver')
    sent_messages = relationship('AnonymousMessage', foreign_keys='AnonymousMessage.sender_id', back_populates='sender')
    received_messages = relationship('AnonymousMessage', foreign_keys='AnonymousMessage.receiver_id',
                                     back_populates='receiver')
    feedbacks_given = relationship('Feedback', foreign_keys='Feedback.giver_id', back_populates='giver')
    feedbacks_received = relationship('Feedback', foreign_keys='Feedback.receiver_id', back_populates='receiver')
    created_invites = relationship('InviteCode', back_populates='creator')
    # admin_notifications = relationship('AdminNotification', foreign_keys='AdminNotification.user_id',
    #                                    back_populates='user')


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

    # Relationships
    creator = relationship("User", back_populates="created_groups")
    members = relationship("User", secondary=user_group_association, back_populates="groups")
    events = relationship("Event", back_populates="group")
    invites = relationship('InviteCode', back_populates='group')
    anonymous_messages = relationship('AnonymousMessage', back_populates='group')
    # admin_notifications = relationship('AdminNotification', back_populates='group')


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

    # Relationships
    group = relationship("Group", back_populates="events")
    results = relationship('DrawResult', back_populates='event')
    feedbacks = relationship('Feedback', back_populates='event')
    exclusion_rules = relationship('ExclusionRule', back_populates='event')


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

    # Relationships
    event = relationship('Event', back_populates='results')
    santa = relationship('User', foreign_keys=[santa_id], back_populates='as_santa')
    receiver = relationship('User', foreign_keys=[receiver_id], back_populates='as_receiver')

    __table_args__ = (
        UniqueConstraint('event_id', 'santa_id', name='unique_event_santa'),
        UniqueConstraint('event_id', 'receiver_id', name='unique_event_receiver'),
        CheckConstraint('santa_id != receiver_id', name='no_self_gift'),
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

    # Relationships
    event = relationship("Event", back_populates="exclusion_rules")
    user1 = relationship("User", foreign_keys=[user1_id])
    user2 = relationship("User", foreign_keys=[user2_id])

    __table_args__ = (
        UniqueConstraint('event_id', 'user1_id', 'user2_id', name='unique_exclusion'),
        CheckConstraint("rule_type IN ('mutual', 'directional')", name='valid_rule_type'),
        CheckConstraint('user1_id != user2_id', name='different_users'),
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

    # Relationships
    sender = relationship('User', foreign_keys=[sender_id], back_populates='sent_messages')
    receiver = relationship('User', foreign_keys=[receiver_id], back_populates='received_messages')
    group = relationship("Group", back_populates="anonymous_messages")


class Feedback(Base):
    __tablename__ = 'feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    giver_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    receiver_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5 stars
    comment = Column(Text, nullable=True)
    is_anonymous = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    # Relationships
    event = relationship('Event', back_populates='feedbacks')
    giver = relationship('User', foreign_keys=[giver_id], back_populates='feedbacks_given')
    receiver = relationship('User', foreign_keys=[receiver_id], back_populates='feedbacks_received')

    __table_args__ = (
        UniqueConstraint('event_id', 'giver_id', 'receiver_id', name='unique_feedback'),
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

    # Relationships
    group = relationship("Group", back_populates="invites")
    creator = relationship("User", back_populates="created_invites")


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

    # Явно указываем foreign_keys для устранения неоднозначности
    user = relationship("User", foreign_keys=[user_id], backref="admin_notifications_received")
    group = relationship("Group", backref="admin_notifications")
    resolver = relationship("User", foreign_keys=[resolved_by], backref="admin_notifications_resolved")

    __table_args__ = (
        Index('idx_notifications_user', 'user_id'),
        Index('idx_notifications_group', 'group_id'),
        Index('idx_notifications_resolved', 'is_resolved'),
        Index('idx_notifications_created', 'created_at'),
    )


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def generate_invite_code(length=8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(length))
        db = SyncSessionLocal()
        existing = db.query(InviteCode).filter_by(code=code).first()
        db.close()
        if not existing:
            return code


# Create tables
Base.metadata.create_all(bind=sync_engine)

# Экспортируем ассоциативную таблицу для импорта
user_group_association = UserGroupAssociation = user_group_association

# Создаем псевдоним для удобства импорта
__all__ = [
    'Base', 'User', 'Group', 'Event', 'DrawResult', 'ExclusionRule',
    'AnonymousMessage', 'Feedback', 'InviteCode', 'AdminNotification',
    'user_group_association', 'UserGroupAssociation',
    'get_async_db', 'generate_invite_code'
]