"""Remember the admin origin while a Telegram link is pending."""

import sqlalchemy as sa

from alembic import op

revision = "0004_telegram_link_origin"
down_revision = "0003_telegram_binding"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("telegram_binding", sa.Column("link_admin_origin", sa.String()))


def downgrade():
    op.drop_column("telegram_binding", "link_admin_origin")
