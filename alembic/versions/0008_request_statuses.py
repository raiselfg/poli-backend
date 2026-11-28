"""Add stages to request processing."""

import sqlalchemy as sa

from alembic import op

revision = "0008_request_statuses"
down_revision = "0007_request_note_attachments"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("chk_requests_status", "requests", type_="check")
    op.create_check_constraint(
        "chk_requests_status",
        "requests",
        "status IN ('new', 'in_progress', 'clarifying', 'quote_sent', 'waiting_reply', "
        "'completed', 'cancelled')",
    )


def downgrade():
    requests = sa.table("requests", sa.column("status", sa.String()))
    stmt = (
        requests.update()
        .where(requests.c.status.in_(["clarifying", "quote_sent", "waiting_reply"]))
        .values(status="in_progress")
    )
    op.execute(stmt)
    stmt = requests.update().where(requests.c.status == "cancelled").values(status="completed")
    op.execute(stmt)
    op.drop_constraint("chk_requests_status", "requests", type_="check")
    op.create_check_constraint(
        "chk_requests_status", "requests", "status IN ('new', 'in_progress', 'completed')"
    )
