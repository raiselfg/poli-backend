"""Remove the category association from requests."""

import sqlalchemy as sa

from alembic import op

revision = "0005_remove_request_category"
down_revision = "0004_telegram_link_origin"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("idx_requests_category_id", table_name="requests")
    op.drop_constraint("fk_requests_category", "requests", type_="foreignkey")
    op.drop_column("requests", "category_id")


def downgrade():
    op.add_column("requests", sa.Column("category_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_requests_category",
        "requests",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_requests_category_id", "requests", ["category_id"])
