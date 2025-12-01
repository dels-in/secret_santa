from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Table, UniqueConstraint, \
    BigInteger, Index, CheckConstraint
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import pytz
import secrets
import string
from typing import AsyncGenerator

from config import DATABASE_URL, SYNC_DATABASE_URL, TIMEZONE

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

    groups = relationship("Group", secondary=user_group_association, back_populates="members")
    created_groups = relationship("Group", back_populates="creator")
    as_santa = relationship('DrawResult', foreign_keys='DrawResult.santa_id', back_populates='santa')
    as_receiver = relationship('DrawResult', foreign_keys='DrawResult.receiver_id', back_populates='receiver')


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

    creator = relationship("User", back_populates="created_groups")
    members = relationship("User", secondary=user_group_association, back_populates="groups")
    events = relationship("Event", back_populates="group")


class Event(Base):
    __tablename__ = 'events'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    group_id = Column(Integer, ForeignKey('groups.id', ondelete='CASCADE'), nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default='waiting', nullable=False)
    price_limit = Column(String(100), nullable=True)
    draw_method = Column(String(20), default='auto', nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.timezone(TIMEZONE)))

    group = relationship("Group", back_populates="events")
    results = relationship('DrawResult', back_populates='event')


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

    event = relationship('Event', back_populates='results')
    santa = relationship('User', foreign_keys=[santa_id], back_populates='as_santa')
    receiver = relationship('User', foreign_keys=[receiver_id], back_populates='as_receiver')

    __table_args__ = (
        UniqueConstraint('event_id', 'santa_id', name='unique_event_santa'),
        UniqueConstraint('event_id', 'receiver_id', name='unique_event_receiver'),
        CheckConstraint('santa_id != receiver_id', name='no_self_gift'),
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


# Only create tables - migrations.py will handle initialization
Base.metadata.create_all(bind=sync_engine)