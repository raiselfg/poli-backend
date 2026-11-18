"""Store media object keys instead of storage URLs."""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("media", sa.Column("object_key", sa.Text(), nullable=True))
    op.execute(
        "UPDATE media SET object_key = "
        "substring(url from '/((catalog|requests)/[^/?#]+)$')"
    )
    op.alter_column("media", "object_key", nullable=False)
    op.create_unique_constraint("media_object_key_key", "media", ["object_key"])
    op.drop_constraint("chk_media_url", "media", type_="check")
    op.drop_column("media", "url")


def downgrade():
    raise NotImplementedError("The original media URL cannot be recovered from its object key.")
