"""Store private attachments for request notes."""

import sqlalchemy as sa

from alembic import op

revision = "0007_request_note_attachments"
down_revision = "0006_request_notes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "request_note_attachments",
        sa.Column(
            "note_id",
            sa.Uuid(),
            sa.ForeignKey(
                "request_notes.id", ondelete="CASCADE", name="fk_request_note_attachments_note"
            ),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column(
            "media_id",
            sa.Uuid(),
            sa.ForeignKey(
                "media.id", ondelete="RESTRICT", name="fk_request_note_attachments_media"
            ),
            nullable=False,
            unique=True,
        ),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 4", name="chk_request_note_attachments_position"
        ),
    )


def downgrade():
    op.drop_table("request_note_attachments")
