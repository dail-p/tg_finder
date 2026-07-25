from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=datetime.utcnow
    )

    packs: Mapped[list[ChannelPack]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[str] = mapped_column(Text, unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=datetime.utcnow
    )
    last_indexed_message_id: Mapped[int | None] = mapped_column(BigInteger)

    posts: Mapped[list[Post]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )
    packs: Mapped[list[PackChannel]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )


class ChannelPack(Base):
    __tablename__ = "channel_packs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=datetime.utcnow
    )

    owner: Mapped[User] = relationship(back_populates="packs")
    channels: Mapped[list[PackChannel]] = relationship(
        back_populates="pack", cascade="all, delete-orphan"
    )


class PackChannel(Base):
    __tablename__ = "pack_channels"

    pack_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channel_packs.id", ondelete="CASCADE"), primary_key=True
    )
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True
    )

    pack: Mapped[ChannelPack] = relationship(back_populates="channels")
    channel: Mapped[Channel] = relationship(back_populates="packs")


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("channel_id", "telegram_message_id", name="uq_post_channel_msg"),
        Index("ix_posts_posted_at", text("posted_at DESC NULLS LAST")),
        Index("ix_posts_channel_posted_at", "channel_id", text("posted_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    telegram_message_id: Mapped[int] = mapped_column(BigInteger)
    content: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="", server_default="")
    hashtags: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    media: Mapped[list[dict]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    grouped_id: Mapped[int | None] = mapped_column(BigInteger)
    media_type: Mapped[str | None] = mapped_column(String(32))
    posted_at: Mapped[datetime | None] = mapped_column()
    indexed_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=datetime.utcnow
    )

    channel: Mapped[Channel] = relationship(back_populates="posts")
