"""initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "hashtags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "media",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("grouped_id", sa.BigInteger(), nullable=True),
        sa.Column("media_type", sa.String(length=32), nullable=True),
        sa.Column("posted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("indexed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("channel_id", "telegram_message_id", name="uq_post_channel_msg"),
    )
    op.create_index("ix_posts_channel_id", "posts", ["channel_id"])
    # Freshness ordering for the title-selection step.
    op.create_index("ix_posts_posted_at", "posts", [sa.text("posted_at DESC NULLS LAST")])
    # Ready for the (out-of-scope) per-channel filter.
    op.create_index(
        "ix_posts_channel_posted_at",
        "posts",
        ["channel_id", sa.text("posted_at DESC")],
    )
    # Kept as a hook for an FTS pre-filter if the token budget stops coping.
    op.create_index(
        "idx_posts_content_fts",
        "posts",
        [sa.text("to_tsvector('russian', content)")],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("idx_posts_content_fts", table_name="posts")
    op.drop_index("ix_posts_channel_posted_at", table_name="posts")
    op.drop_index("ix_posts_posted_at", table_name="posts")
    op.drop_index("ix_posts_channel_id", table_name="posts")
    op.drop_table("posts")

    op.drop_table("pack_channels")
    op.drop_table("channel_packs")

    op.drop_index("ix_channels_telegram_id", table_name="channels")
    op.drop_table("channels")

    op.drop_table("users")
