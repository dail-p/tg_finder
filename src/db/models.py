from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.config import settings
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
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    telegram_message_id: Mapped[int] = mapped_column(BigInteger)
    content: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(32))
    posted_at: Mapped[datetime | None] = mapped_column()
    indexed_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=datetime.utcnow
    )

    channel: Mapped[Channel] = relationship(back_populates="posts")
    chunks: Mapped[list[PostChunk]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class PostChunk(Base):
    __tablename__ = "post_chunks"
    __table_args__ = (
        Index("ix_post_chunks_post_id", "post_id"),
        Index(
            "ix_post_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("posts.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list | None] = mapped_column(Vector(settings.embedding_dim))
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=datetime.utcnow
    )

    post: Mapped[Post] = relationship(back_populates="chunks")
