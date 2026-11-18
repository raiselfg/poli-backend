"""Allow up to three attachments per request."""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "request_attachments",
        sa.Column(
            "request_id",
            sa.Uuid(),
            sa.ForeignKey("requests.id", ondelete="CASCADE", name="fk_request_attachments_request"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column(
            "media_id",
            sa.Uuid(),
            sa.ForeignKey("media.id", ondelete="RESTRICT", name="fk_request_attachments_media"),
            nullable=False,
            unique=True,
        ),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 2", name="chk_request_attachments_position"
        ),
    )
    op.execute(
        "INSERT INTO request_attachments (request_id, position, media_id) "
        "SELECT id, 0, media_id FROM requests WHERE media_id IS NOT NULL"
    )
    op.drop_column("requests", "media_id")


def downgrade():
    raise NotImplementedError("Downgrading could discard additional request attachments.")
