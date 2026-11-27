"""Store internal notes on requests."""

import sqlalchemy as sa

from alembic import op

revision = "0006_request_notes"
down_revision = "0005_remove_request_category"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "request_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "request_id",
            sa.Uuid(),
            sa.ForeignKey("requests.id", ondelete="CASCADE", name="fk_request_notes_request"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "idx_request_notes_request_created_at", "request_notes", ["request_id", "created_at", "id"]
    )


def downgrade():
    op.drop_table("request_notes")
