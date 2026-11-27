"""Store the available WebP variants for catalog images."""

import sqlalchemy as sa

from alembic import op

revision = "0002_catalog_image_variants"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("media", sa.Column("catalog_variants", sa.JSON(none_as_null=True)))


def downgrade():
    op.drop_column("media", "catalog_variants")
