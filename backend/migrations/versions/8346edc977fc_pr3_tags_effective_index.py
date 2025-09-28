"""PR3 tags effective index"""

from __future__ import annotations

from typing import Iterable

from alembic import op
import sqlalchemy as sa


revision = "8346edc977fc"
down_revision = "dde21381ed8c"
branch_labels = None
depends_on = None


CURRENT_TS = sa.text("CURRENT_TIMESTAMP")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return any(col["name"] == column for col in _inspector().get_columns(table))


def _has_index(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    return any(ix["name"] == name for ix in _inspector().get_indexes(table))


def _execute(sql: str, **params) -> None:
    op.execute(sa.text(sql).bindparams(**{k: sa.bindparam(k, v) for k, v in params.items()}))


def _ensure_tags_columns() -> None:
    if not _has_table("tags"):
        return
    # ensure optional columns exist for PR3 semantics
    if not _has_column("tags", "color"):
        op.add_column("tags", sa.Column("color", sa.String(length=32), nullable=True))
    if not _has_column("tags", "description"):
        op.add_column("tags", sa.Column("description", sa.Text(), nullable=True))
    if not _has_column("tags", "is_deprecated"):
        op.add_column("tags", sa.Column("is_deprecated", sa.Boolean(), server_default=sa.text("0"), nullable=False))
    if not _has_column("tags", "created_at"):
        op.add_column(
            "tags",
            sa.Column("created_at", sa.DateTime(), server_default=CURRENT_TS, nullable=False),
        )
    if not _has_column("tags", "updated_at"):
        op.add_column(
            "tags",
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=CURRENT_TS,
                nullable=False,
            ),
        )
    if not _has_index("tags", "ix_tags_lower_name"):
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_tags_lower_name ON tags(LOWER(name))"))


def _create_tag_assignments() -> None:
    if _has_table("tag_assignments"):
        return

    op.create_table(
        "tag_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=CURRENT_TS),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=CURRENT_TS,
        ),
        sa.CheckConstraint(
            "entity_type IN ('budget','item_project','category','entry','line_asset','vendor')",
            name="ck_tag_assignments_entity_type",
        ),
        sa.UniqueConstraint(
            "tag_id",
            "entity_type",
            "entity_id",
            "scope",
            name="uq_tag_assignments_scope",
        ),
    )

    op.create_index(
        "ix_tag_assignments_entity",
        "tag_assignments",
        ["entity_type", "entity_id"],
    )
    op.create_index(
        "ix_tag_assignments_tag_id",
        "tag_assignments",
        ["tag_id"],
    )


def _create_effective_tag_index() -> None:
    if _has_table("effective_tag_index"):
        return

    op.create_table(
        "effective_tag_index",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("path_ids", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=CURRENT_TS),
        sa.UniqueConstraint(
            "entity_type",
            "entity_id",
            "tag_id",
            "scope",
            name="uq_effective_tag_index_unique",
        ),
    )

    op.create_index(
        "ix_effective_tag_index_entity",
        "effective_tag_index",
        ["entity_type", "entity_id"],
    )
    op.create_index(
        "ix_effective_tag_index_tag",
        "effective_tag_index",
        ["tag_id"],
    )


def _create_background_jobs() -> None:
    if _has_table("background_jobs"):
        return

    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=CURRENT_TS),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=CURRENT_TS),
        sa.CheckConstraint(
            "status IN ('queued','running','success','error')",
            name="ck_background_jobs_status",
        ),
    )

    op.create_index(
        "ix_background_jobs_kind",
        "background_jobs",
        ["kind"],
    )
    op.create_index(
        "ix_background_jobs_status",
        "background_jobs",
        ["status"],
    )


def _create_audit_events() -> None:
    if _has_table("audit_events"):
        return

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=CURRENT_TS),
    )

    op.create_index(
        "ix_audit_events_event_type",
        "audit_events",
        ["event_type"],
    )
    op.create_index(
        "ix_audit_events_created_at",
        "audit_events",
        ["created_at"],
    )


def _create_view_effective_tags_flat() -> None:
    op.execute(
        sa.text(
            """
            CREATE VIEW IF NOT EXISTS v_effective_tags_flat AS
            SELECT
                eti.id AS id,
                eti.entity_type,
                eti.entity_id,
                eti.tag_id,
                eti.scope,
                eti.source,
                eti.path_ids,
                eti.created_at,
                t.name AS tag_name,
                t.color AS tag_color,
                t.is_deprecated AS tag_is_deprecated
            FROM effective_tag_index AS eti
            JOIN tags AS t ON t.id = eti.tag_id
            """
        )
    )


def _migrate_entry_tags() -> None:
    if not _has_table("entry_tags") or not _has_table("tag_assignments"):
        return

    _execute(
        """
        INSERT OR IGNORE INTO tag_assignments (tag_id, entity_type, entity_id, scope, created_at, updated_at)
        SELECT tag_id, 'entry', entry_id, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM entry_tags
        """
    )


def _drop_indexes(table: str, names: Iterable[str]) -> None:
    for name in names:
        if _has_index(table, name):
            op.drop_index(name, table_name=table)


# ---------------------------------------------------------------------------
# main migration entry points
# ---------------------------------------------------------------------------

def upgrade() -> None:
    _ensure_tags_columns()
    _create_tag_assignments()
    _create_effective_tag_index()
    _create_background_jobs()
    _create_audit_events()
    _create_view_effective_tags_flat()
    _migrate_entry_tags()


def downgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS v_effective_tags_flat"))

    if _has_table("audit_events"):
        _drop_indexes("audit_events", ["ix_audit_events_event_type", "ix_audit_events_created_at"])
        op.drop_table("audit_events")

    if _has_table("background_jobs"):
        _drop_indexes("background_jobs", ["ix_background_jobs_kind", "ix_background_jobs_status"])
        op.drop_table("background_jobs")

    if _has_table("effective_tag_index"):
        _drop_indexes(
            "effective_tag_index",
            ["ix_effective_tag_index_entity", "ix_effective_tag_index_tag"],
        )
        op.drop_table("effective_tag_index")

    if _has_table("tag_assignments"):
        _drop_indexes(
            "tag_assignments",
            ["ix_tag_assignments_entity", "ix_tag_assignments_tag_id"],
        )
        op.drop_table("tag_assignments")

    # optional: drop the lower(name) index if present
    if _has_index("tags", "ix_tags_lower_name"):
        op.execute(sa.text("DROP INDEX IF EXISTS ix_tags_lower_name"))
