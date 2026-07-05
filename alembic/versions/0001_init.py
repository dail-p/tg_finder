"""initial schema with pgvector

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op
from src.config import settings

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("last_indexed_message_id", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_channels_telegram_id", "channels", ["telegram_id"])

    op.create_table(
        "channel_packs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "pack_channels",
        sa.Column("pack_id", sa.Integer(), sa.ForeignKey("channel_packs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=True),
        sa.Column("posted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("indexed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("channel_id", "telegram_message_id", name="uq_post_channel_msg"),
    )
    op.create_index("ix_posts_channel_id", "posts", ["channel_id"])
    op.create_index(
        "idx_posts_content_fts",
        "posts",
        [sa.text("to_tsvector('russian', content)")],
        postgresql_using="gin",
    )

    op.create_table(
        "post_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(settings.embedding_dim), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_post_chunks_post_id", "post_chunks", ["post_id"])
    op.create_index(
        "ix_post_chunks_embedding_hnsw",
        "post_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_post_chunks_embedding_hnsw", table_name="post_chunks")
    op.drop_index("ix_post_chunks_post_id", table_name="post_chunks")
    op.drop_table("post_chunks")

    op.drop_index("idx_posts_content_fts", table_name="posts")
    op.drop_index("ix_posts_channel_id", table_name="posts")
    op.drop_table("posts")

    op.drop_table("pack_channels")
    op.drop_table("channel_packs")

    op.drop_index("ix_channels_telegram_id", table_name="channels")
    op.drop_table("channels")

    op.drop_table("users")
