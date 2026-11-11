"""Create catalog, contacts, media and requests tables."""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.String(120), nullable=False, unique=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="chk_categories_slug"),
        sa.CheckConstraint("length(btrim(title)) > 0", name="chk_categories_title"),
        sa.CheckConstraint("sort_order >= 0", name="chk_categories_sort_order"),
    )
    op.create_index("idx_categories_sort_order", "categories", ["sort_order", "id"])
    op.create_table(
        "media",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("alt", sa.String(200)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("url ~ '^https?://'", name="chk_media_url"),
        sa.CheckConstraint("size_bytes > 0", name="chk_media_size"),
        sa.CheckConstraint("width IS NULL OR width > 0", name="chk_media_width"),
        sa.CheckConstraint("height IS NULL OR height > 0", name="chk_media_height"),
    )
    op.create_table(
        "category_media",
        sa.Column(
            "category_id",
            sa.Uuid(),
            sa.ForeignKey("categories.id", ondelete="CASCADE", name="fk_category_media_category"),
            primary_key=True,
        ),
        sa.Column(
            "media_id",
            sa.Uuid(),
            sa.ForeignKey("media.id", ondelete="RESTRICT", name="fk_category_media_media"),
            primary_key=True,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("sort_order >= 0", name="chk_category_media_sort_order"),
    )
    op.create_index("idx_category_media_order", "category_media", ["category_id", "sort_order"])
    op.create_index("idx_category_media_media_id", "category_media", ["media_id"])
    op.create_table(
        "contacts",
        sa.Column("id", sa.SmallInteger(), primary_key=True, server_default="1"),
        sa.Column("phone", sa.String(40), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("working_hours", sa.String(255), nullable=False),
        sa.Column("telegram_url", sa.Text(), nullable=False),
        sa.Column("whatsapp_url", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="chk_contacts_singleton"),
        sa.CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude IS NOT NULL AND longitude IS NOT NULL)",
            name="chk_contacts_coordinates",
        ),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="chk_contacts_latitude"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="chk_contacts_longitude"),
    )
    op.execute(
        "INSERT INTO contacts "
        "(id, phone, email, address, latitude, longitude, working_hours, "
        "telegram_url, whatsapp_url) "
        "VALUES (1, '+7 (000) 000-00-00', 'info@example.com', 'Пример адреса', "
        "55.755800, 37.617300, 'Пн–Пт: 9:00–18:00', "
        "'https://example.com/telegram', 'https://example.com/whatsapp')"
    )
    op.create_table(
        "requests",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(40), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column(
            "category_id",
            sa.Uuid(),
            sa.ForeignKey("categories.id", ondelete="SET NULL", name="fk_requests_category"),
        ),
        sa.Column(
            "media_id",
            sa.Uuid(),
            sa.ForeignKey("media.id", ondelete="RESTRICT", name="fk_requests_media"),
            unique=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="chk_requests_name"),
        sa.CheckConstraint("length(btrim(phone)) > 0", name="chk_requests_phone"),
        sa.CheckConstraint(
            "status IN ('new', 'in_progress', 'completed')", name="chk_requests_status"
        ),
    )
    op.create_index(
        "idx_requests_created_at", "requests", [sa.text("created_at DESC"), sa.text("id DESC")]
    )
    op.create_index(
        "idx_requests_status_created_at", "requests", ["status", sa.text("created_at DESC")]
    )
    op.create_index("idx_requests_category_id", "requests", ["category_id"])


def downgrade():
    op.drop_table("requests")
    op.drop_table("contacts")
    op.drop_table("category_media")
    op.drop_table("media")
    op.drop_table("categories")
