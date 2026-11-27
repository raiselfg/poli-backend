"""Store the chat for Telegram request notifications."""

import sqlalchemy as sa

from alembic import op

revision = "0003_telegram_binding"
down_revision = "0002_catalog_image_variants"
branch_labels = None
depends_on = None


def upgrade():
    binding = op.create_table(
        "telegram_binding",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger()),
        sa.Column("admin_origin", sa.String()),
        sa.Column("bot_token_hash", sa.String(64)),
        sa.Column("link_hash", sa.String(64)),
        sa.Column("link_expires_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("id = 1", name="chk_telegram_binding_singleton"),
    )
    op.bulk_insert(binding, [{"id": 1}])


def downgrade():
    op.drop_table("telegram_binding")
