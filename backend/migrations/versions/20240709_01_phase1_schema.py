"""Phase 1 schema foundations for unified budgets/tags overhaul"""

from __future__ import annotations

import json
from decimal import Decimal

from alembic import op
import sqlalchemy as sa
from sqlalchemy import orm, text, select

from backend import models, models_finance  # noqa: F401 - ensure metadata loads
from backend.scripts.reconcile_ledgers import reconcile_ledgers


revision = "20240709_01"
down_revision = "20230915_01"
branch_labels = None
depends_on = None


CURRENT_TS = sa.text("CURRENT_TIMESTAMP")


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)

def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names()


def _has_index(table: str, name: str) -> bool:
    conn = op.get_bind()
    rows = conn.exec_driver_sql(f"PRAGMA index_list({table})").fetchall()
    return any(r[1] == name for r in rows)



def _fk_exists(table: str, ref_table: str, local_cols: list[str], remote_cols: list[str]) -> bool:
    conn = op.get_bind()
    rows = conn.exec_driver_sql(f"PRAGMA foreign_key_list({table})").fetchall()
    constraints: dict[int, dict[str, list[tuple[str, str]]]] = {}
    for row in rows:
        fk_id = row[0]
        info = constraints.setdefault(fk_id, {"table": row[2], "mapping": []})
        info["mapping"].append((row[3], row[4]))
    target = sorted(zip(local_cols, remote_cols), key=lambda x: x[0])
    for info in constraints.values():
        if info["table"] != ref_table:
            continue
        mapping = sorted(info["mapping"], key=lambda x: x[0])
        if mapping == target:
            return True
    return False



def _scalar(sql: str) -> int:
    conn = op.get_bind()
    return conn.exec_driver_sql(sql).scalar_one()


def _rowcount(sql: str) -> int:
    conn = op.get_bind()
    result = conn.exec_driver_sql(sql)
    return getattr(result, 'rowcount', 0)


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if not _has_column(table, column.name):
        op.add_column(table, column)



def add_timestamp_columns_sqlite_safe(table: str, *, include_audit: bool = True) -> None:
    _add_column_if_missing(table, sa.Column("created_at", sa.DateTime(), nullable=True))
    _add_column_if_missing(table, sa.Column("updated_at", sa.DateTime(), nullable=True))
    if include_audit:
        _add_column_if_missing(table, sa.Column("created_by", sa.Text(), nullable=True))
        _add_column_if_missing(table, sa.Column("updated_by", sa.Text(), nullable=True))
    op.execute(sa.text(
        f"""
        UPDATE {table}
        SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
            updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
        """
    ))
    with op.batch_alter_table(table) as batch:
        batch.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )
        batch.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )



def _add_funding_source_columns():
    _add_column_if_missing("funding_sources", sa.Column("owner", sa.String(length=255), nullable=True))
    _add_column_if_missing("funding_sources", sa.Column("is_cost_center", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    _add_column_if_missing("funding_sources", sa.Column("description", sa.Text(), nullable=True))
    _add_column_if_missing("funding_sources", sa.Column("budget_amount_cache", sa.Numeric(18, 2), nullable=True))
    add_timestamp_columns_sqlite_safe("funding_sources", include_audit=True)
        

def _extend_projects_table():
    _add_column_if_missing("projects", sa.Column("budget_id", sa.Integer(), nullable=True))
    _add_column_if_missing("projects", sa.Column("description", sa.Text(), nullable=True))
    _add_column_if_missing("projects", sa.Column("legacy_portfolio_id", sa.Integer(), nullable=True))
    add_timestamp_columns_sqlite_safe("projects", include_audit=False)
        



def _ensure_unassigned_budget() -> int:
    op.execute(sa.text("""
        INSERT INTO funding_sources (name, type, is_cost_center, is_temporary, created_at, updated_at)
        SELECT 'Unassigned', 'COST_CENTER', 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        WHERE NOT EXISTS (
            SELECT 1 FROM funding_sources WHERE name = 'Unassigned'
        )
    """))
    return _scalar("SELECT id FROM funding_sources WHERE name = 'Unassigned' LIMIT 1")


def _backfill_project_budgets(unassigned_id: int) -> None:
    op.execute(sa.text("""
        UPDATE projects
        SET budget_id = (
            SELECT fs.id
            FROM funding_sources fs
            WHERE fs.legacy_portfolio_id = projects.portfolio_id
        )
        WHERE budget_id IS NULL
          AND portfolio_id IS NOT NULL
    """))
    op.execute(
        sa.text("""
            UPDATE projects
            SET budget_id = :default_id
            WHERE budget_id IS NULL
        """)
        .bindparams(sa.bindparam("default_id", unassigned_id))
    )

def _augment_categories_table(unassigned_id: int) -> None:
    _add_column_if_missing("categories", sa.Column("item_project_id", sa.Integer(), nullable=True))
    _add_column_if_missing("categories", sa.Column("budget_id", sa.Integer(), nullable=True))
    _add_column_if_missing("categories", sa.Column("description", sa.Text(), nullable=True))
    _add_column_if_missing("categories", sa.Column("is_leaf", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    _add_column_if_missing("categories", sa.Column("amount_leaf", sa.Numeric(18, 2), nullable=True))
    _add_column_if_missing("categories", sa.Column("rollup_amount", sa.Numeric(18, 2), nullable=True))
    _add_column_if_missing("categories", sa.Column("path_ids", sa.JSON(), nullable=True))
    _add_column_if_missing("categories", sa.Column("path_names", sa.JSON(), nullable=True))
    _add_column_if_missing("categories", sa.Column("path_depth", sa.Integer(), nullable=True))
    _add_column_if_missing("categories", sa.Column("created_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("categories", sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.execute(sa.text("""
        UPDATE categories
        SET item_project_id = COALESCE(item_project_id, project_id)
    """))

    while True:
        changed = _rowcount(
            """
            UPDATE categories AS c
            SET item_project_id = (
                SELECT p.item_project_id FROM categories AS p WHERE p.id = c.parent_id
            )
            WHERE c.item_project_id IS NULL
              AND c.parent_id IS NOT NULL
              AND (SELECT p.item_project_id FROM categories AS p WHERE p.id = c.parent_id) IS NOT NULL
            """
        )
        if not changed:
            break

    op.execute(
        sa.text("""
            UPDATE categories AS c
            SET budget_id = COALESCE(
                c.budget_id,
                (SELECT p.budget_id FROM projects AS p WHERE p.id = c.item_project_id),
                :default_id
            )
            WHERE c.budget_id IS NULL
        """)
        .bindparams(sa.bindparam("default_id", unassigned_id))
    )

    while True:
        changed = _rowcount(
            """
            UPDATE categories AS c
            SET budget_id = (
                SELECT p.budget_id FROM categories AS p WHERE p.id = c.parent_id
            )
            WHERE c.budget_id IS NULL
              AND c.parent_id IS NOT NULL
              AND (SELECT p.budget_id FROM categories AS p WHERE p.id = c.parent_id) IS NOT NULL
            """
        )
        if not changed:
            break

    op.execute(sa.text("""
        UPDATE categories
        SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
            updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
    """))

    null_budget = _scalar("SELECT COUNT(*) FROM categories WHERE budget_id IS NULL")

    if null_budget > 0:
        op.execute(
            sa.text("""
                UPDATE categories
                SET budget_id = :default_id
                WHERE budget_id IS NULL
            """)
            .bindparams(sa.bindparam("default_id", unassigned_id))
        )
        null_budget = 0

    if null_budget == 0:
        with op.batch_alter_table("categories") as batch:
            batch.alter_column("budget_id", existing_type=sa.Integer(), nullable=False)
            if not _fk_exists("categories", "funding_sources", ["budget_id"], ["id"]):
                batch.create_foreign_key(
                    "fk_categories_budget_id_funding_sources_id",
                    "funding_sources",
                    ["budget_id"],
                    ["id"],
                    ondelete="CASCADE",
                )




def _extend_entries_table():
    _add_column_if_missing("entries", sa.Column("item_project_id", sa.Integer(), nullable=True))
    if not _has_index("entries", "ix_entries_item_project"):
        op.create_index("ix_entries_item_project", "entries", ["item_project_id"] )


def _extend_tags_table():
    _add_column_if_missing("tags", sa.Column("color", sa.String(length=50), nullable=True))
    _add_column_if_missing("tags", sa.Column("description", sa.Text(), nullable=True))
    _add_column_if_missing("tags", sa.Column("is_deprecated", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    add_timestamp_columns_sqlite_safe("tags", include_audit=False)


def _create_line_asset_tables():
    if not _has_table("line_assets"):
        op.create_table(
            "line_assets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=CURRENT_TS),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=CURRENT_TS),
        )

    if not _has_table("item_project_line_assets"):
        op.create_table(
            "item_project_line_assets",
            sa.Column("item_project_id", sa.Integer(), nullable=False),
            sa.Column("line_asset_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=CURRENT_TS),
            sa.ForeignKeyConstraint(["item_project_id"], ["projects.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["line_asset_id"], ["line_assets.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("item_project_id", "line_asset_id"),
        )

    if not _has_index("item_project_line_assets", "ix_item_project_line_assets_item"):
        op.create_index("ix_item_project_line_assets_item", "item_project_line_assets", ["item_project_id"])
    if not _has_index("item_project_line_assets", "ix_item_project_line_assets_line"):
        op.create_index("ix_item_project_line_assets_line", "item_project_line_assets", ["line_asset_id"])


def _create_allocations_table():
    if not _has_table("allocations"):
        op.create_table(
            "allocations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("entry_id", sa.Integer(), nullable=False),
            sa.Column("item_project_id", sa.Integer(), nullable=False),
            sa.Column("category_id", sa.Integer(), nullable=False),
            sa.Column("budget_id", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("currency", sa.String(length=10), nullable=True),
            sa.Column("posted_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    else:
        _add_column_if_missing("allocations", sa.Column("item_project_id", sa.Integer(), nullable=False))
        _add_column_if_missing("allocations", sa.Column("category_id", sa.Integer(), nullable=False))
        _add_column_if_missing("allocations", sa.Column("budget_id", sa.Integer(), nullable=False))
        _add_column_if_missing("allocations", sa.Column("currency", sa.String(length=10), nullable=True))
        _add_column_if_missing("allocations", sa.Column("posted_at", sa.DateTime(), nullable=True))
        _add_column_if_missing("allocations", sa.Column("created_at", sa.DateTime(), nullable=True))
        _add_column_if_missing("allocations", sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.execute(sa.text(
        """
        UPDATE allocations
        SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
            updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
        """
    ))
    with op.batch_alter_table("allocations") as batch:
        batch.alter_column("created_at", existing_type=sa.DateTime(), nullable=False)
        batch.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)

    if not _has_index("allocations", "ix_allocations_entry"):
        op.create_index("ix_allocations_entry", "allocations", ["entry_id"])
    if not _has_index("allocations", "ix_allocations_item_category"):
        op.create_index("ix_allocations_item_category", "allocations", ["item_project_id", "category_id"])
    if not _has_index("allocations", "ix_allocations_budget"):
        op.create_index("ix_allocations_budget", "allocations", ["budget_id"])

def _create_journal_tables():
    if not _has_table("journal_entries"):
        op.create_table(
            "journal_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_entry_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=CURRENT_TS),
            sa.Column("created_by", sa.String(length=100), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["source_entry_id"], ["entries.id"], ondelete="SET NULL"),
        )
    if not _has_table("journal_postings"):
        op.create_table(
            "journal_postings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("journal_entry_id", sa.Integer(), nullable=False),
            sa.Column("allocation_id", sa.Integer(), nullable=True),
            sa.Column("item_project_id", sa.Integer(), nullable=False),
            sa.Column("category_id", sa.Integer(), nullable=False),
            sa.Column("budget_id", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("posted_at", sa.DateTime(), nullable=False, server_default=CURRENT_TS),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=CURRENT_TS),
            sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["allocation_id"], ["allocations.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["item_project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["budget_id"], ["funding_sources.id"], ondelete="CASCADE"),
        )
    if not _has_index("journal_postings", "ix_journal_postings_entry"):
        op.create_index("ix_journal_postings_entry", "journal_postings", ["journal_entry_id"])
    if not _has_index("journal_postings", "ix_journal_postings_budget"):
        op.create_index("ix_journal_postings_budget", "journal_postings", ["budget_id"])

TRIGGER_CATEGORY_AMOUNT_GUARD = """
CREATE TRIGGER IF NOT EXISTS trg_categories_amount_guard
BEFORE UPDATE ON categories
BEGIN
    SELECT CASE
        WHEN NEW.amount_leaf IS NOT NULL
             AND EXISTS (SELECT 1 FROM categories c WHERE c.parent_id = NEW.id)
        THEN RAISE(ABORT, 'amount_leaf allowed only on leaf categories')
    END;
END;
"""




TRIGGER_CATEGORY_AFTER_INSERT = """
CREATE TRIGGER IF NOT EXISTS trg_categories_after_insert
AFTER INSERT ON categories
BEGIN
    UPDATE categories
    SET is_leaf = CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM categories child
                WHERE child.parent_id = categories.id
            )
            THEN 1 ELSE 0 END,
        amount_leaf = CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM categories child
                WHERE child.parent_id = categories.id
            )
            THEN amount_leaf ELSE NULL END
    WHERE budget_id = NEW.budget_id;

    UPDATE categories
    SET rollup_amount = (
        WITH RECURSIVE subtree(id) AS (
            SELECT categories.id
            UNION ALL
            SELECT c.id
            FROM categories c
            JOIN subtree s ON c.parent_id = s.id
        )
        SELECT COALESCE(SUM(x.amount_leaf), 0)
        FROM categories x
        WHERE x.is_leaf = 1
          AND x.id IN (SELECT id FROM subtree)
    )
    WHERE budget_id = NEW.budget_id;

    UPDATE funding_sources
    SET budget_amount_cache = CASE
            WHEN is_cost_center THEN NULL
            ELSE (
                SELECT COALESCE(SUM(leaf.amount_leaf), 0)
                FROM categories leaf
                WHERE leaf.budget_id = NEW.budget_id
                  AND leaf.is_leaf = 1
            )
        END,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.budget_id;
END;
"""

TRIGGER_CATEGORY_AFTER_DELETE = """
CREATE TRIGGER IF NOT EXISTS trg_categories_after_delete
AFTER DELETE ON categories
BEGIN
    UPDATE categories
    SET is_leaf = CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM categories child
                WHERE child.parent_id = categories.id
            )
            THEN 1 ELSE 0 END,
        amount_leaf = CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM categories child
                WHERE child.parent_id = categories.id
            )
            THEN amount_leaf ELSE NULL END
    WHERE budget_id = OLD.budget_id;

    UPDATE categories
    SET rollup_amount = (
        WITH RECURSIVE subtree(id) AS (
            SELECT categories.id
            UNION ALL
            SELECT c.id
            FROM categories c
            JOIN subtree s ON c.parent_id = s.id
        )
        SELECT COALESCE(SUM(x.amount_leaf), 0)
        FROM categories x
        WHERE x.is_leaf = 1
          AND x.id IN (SELECT id FROM subtree)
    )
    WHERE budget_id = OLD.budget_id;

    UPDATE funding_sources
    SET budget_amount_cache = CASE
            WHEN is_cost_center THEN NULL
            ELSE (
                SELECT COALESCE(SUM(leaf.amount_leaf), 0)
                FROM categories leaf
                WHERE leaf.budget_id = OLD.budget_id
                  AND leaf.is_leaf = 1
            )
        END,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = OLD.budget_id;
END;
"""

TRIGGER_CATEGORY_AFTER_UPDATE = """
CREATE TRIGGER IF NOT EXISTS trg_categories_after_update
AFTER UPDATE ON categories
BEGIN
    UPDATE categories
    SET is_leaf = CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM categories child
                WHERE child.parent_id = categories.id
            )
            THEN 1 ELSE 0 END,
        amount_leaf = CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM categories child
                WHERE child.parent_id = categories.id
            )
            THEN amount_leaf ELSE NULL END
    WHERE budget_id IN (COALESCE(NEW.budget_id, OLD.budget_id));

    UPDATE categories
    SET rollup_amount = (
        WITH RECURSIVE subtree(id) AS (
            SELECT categories.id
            UNION ALL
            SELECT c.id
            FROM categories c
            JOIN subtree s ON c.parent_id = s.id
        )
        SELECT COALESCE(SUM(x.amount_leaf), 0)
        FROM categories x
        WHERE x.is_leaf = 1
          AND x.id IN (SELECT id FROM subtree)
    )
    WHERE budget_id IN (COALESCE(NEW.budget_id, OLD.budget_id));

    UPDATE funding_sources
    SET budget_amount_cache = CASE
            WHEN is_cost_center THEN NULL
            ELSE (
                SELECT COALESCE(SUM(leaf.amount_leaf), 0)
                FROM categories leaf
                WHERE leaf.budget_id = funding_sources.id
                  AND leaf.is_leaf = 1
            )
        END,
        updated_at = CURRENT_TIMESTAMP
    WHERE id IN (COALESCE(NEW.budget_id, OLD.budget_id));
END;
"""

TRIGGER_ALLOCATIONS_GUARD_INSERT = """
CREATE TRIGGER IF NOT EXISTS trg_allocations_guard_insert
BEFORE INSERT ON allocations
BEGIN
    SELECT CASE
        WHEN NEW.category_id IS NULL THEN RAISE(ABORT, 'allocation requires category')
        WHEN (SELECT is_leaf FROM categories WHERE id = NEW.category_id) != 1
            THEN RAISE(ABORT, 'allocations must reference leaf categories')
        WHEN (SELECT project_id FROM categories WHERE id = NEW.category_id) != NEW.item_project_id
            THEN RAISE(ABORT, 'category must belong to allocation item_project')
    END;
END;
"""

TRIGGER_ALLOCATIONS_GUARD_UPDATE = """
CREATE TRIGGER IF NOT EXISTS trg_allocations_guard_update
BEFORE UPDATE ON allocations
BEGIN
    SELECT CASE
        WHEN NEW.category_id IS NULL THEN RAISE(ABORT, 'allocation requires category')
        WHEN (SELECT is_leaf FROM categories WHERE id = NEW.category_id) != 1
            THEN RAISE(ABORT, 'allocations must reference leaf categories')
        WHEN (SELECT project_id FROM categories WHERE id = NEW.category_id) != NEW.item_project_id
            THEN RAISE(ABORT, 'category must belong to allocation item_project')
    END;
END;
"""




def _backfill_allocations(session: orm.Session) -> int:
    entries = session.execute(
        select(models.Entry)).scalars().all()
    allocation_rows = []
    for entry in entries:
        item_project_id = entry.item_project_id or entry.project_id
        category_id = entry.category_id
        if not item_project_id or not category_id:
            continue
        category = session.get(models.Category, category_id)
        if not category or category.item_project_id != item_project_id or not category.is_leaf:
            continue
        payload = {
            "entry_id": entry.id,
            "item_project_id": item_project_id,
            "category_id": category_id,
            "budget_id": category.budget_id,
            "amount": Decimal(str(entry.amount)),
            "currency": "USD",
        }
        if entry.date:
            payload["posted_at"] = entry.date
        allocation_rows.append(payload)
    if allocation_rows:
        session.execute(sa.insert(models.Allocation.__table__), allocation_rows)
    session.commit()
    return len(allocation_rows)

def upgrade() -> None:
    bind = op.get_bind()

    _add_funding_source_columns()
    _extend_projects_table()
    unassigned_id = _ensure_unassigned_budget()
    if unassigned_id is None:
        raise RuntimeError('Unassigned funding source missing')
    _backfill_project_budgets(unassigned_id)
    _augment_categories_table(unassigned_id)
    _extend_entries_table()
    _extend_tags_table()
    _create_line_asset_tables()
    _create_allocations_table()
    _create_journal_tables()

    # Backfill structural FKs and derived columns using ORM for convenience
    session = orm.Session(bind=bind)

    # funding_sources owner/is_cost_center
    session.execute(
        text(
            "UPDATE funding_sources SET owner = COALESCE(owner, legacy_owner), "
            "is_cost_center = CASE WHEN UPPER(COALESCE(type, 'COST_CENTER')) = 'COST_CENTER' THEN 1 ELSE 0 END"
        )
    )

    session.execute(
        sa.text("""
        UPDATE funding_sources
        SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
            updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
        """))
    session.commit()

    # projects budget linkage
    session.execute(
        text(
            "UPDATE projects SET budget_id = COALESCE(budget_id, portfolio_id), "
            "legacy_portfolio_id = COALESCE(legacy_portfolio_id, portfolio_id)"
        )
    )

    # categories budget linkage
    session.execute(
        text(
            """
            UPDATE categories
            SET budget_id = COALESCE((
                SELECT budget_id
                FROM projects
                WHERE projects.id = categories.project_id
            ), :default_id)
            """
        ),
        {"default_id": unassigned_id}
    )
    session.execute(
        text(
            """
            UPDATE categories
            SET is_leaf = CASE
                WHEN NOT EXISTS (
                    SELECT 1
                    FROM categories child
                    WHERE child.parent_id = categories.id
                )
                THEN 1
                ELSE 0
            END
            """
        )
    )
    session.execute(
        text("UPDATE categories SET amount_leaf = CASE WHEN is_leaf = 1 THEN COALESCE(amount_leaf, 0) ELSE NULL END")
    )
    session.execute(text("UPDATE categories SET rollup_amount = amount_leaf WHERE is_leaf = 1"))

    # entries ensure item_project_id mirrors project for now
    session.execute(
        text(
            "UPDATE entries SET item_project_id = COALESCE(item_project_id, project_id)"
        )
    )

    session.commit()

    # Ensure NOT NULL on projects.budget_id / categories.budget_id after backfill
    if _scalar("SELECT COUNT(*) FROM projects WHERE budget_id IS NULL") == 0:
        with op.batch_alter_table("projects", recreate="always") as batch:
            batch.alter_column("budget_id", nullable=False)
            if not _fk_exists("projects", "funding_sources", ["budget_id"], ["id"]):
                batch.create_foreign_key(
                    "fk_projects_budget_id_funding_sources_id",
                    "funding_sources",
                    ["budget_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
    if _scalar("SELECT COUNT(*) FROM categories WHERE budget_id IS NULL") == 0:
        with op.batch_alter_table("categories", recreate="always") as batch:
            batch.alter_column("budget_id", nullable=False)
            if not _fk_exists("categories", "funding_sources", ["budget_id"], ["id"]):
                batch.create_foreign_key(
                    "fk_categories_budget_id_funding_sources_id",
                    "funding_sources",
                    ["budget_id"],
                    ["id"],
                    ondelete="CASCADE",
                )

    # Backfill allocations 1:1 with entries where possible
    session = orm.Session(bind=bind)
    _backfill_allocations(session)

    # Rebuild paths / rollups / budget caches via reconciler helper
    reconcile_ledgers(session)
    session.close()

    # Create triggers after data is consistent
    op.execute(TRIGGER_CATEGORY_AMOUNT_GUARD)
    op.execute(TRIGGER_CATEGORY_AFTER_INSERT)
    op.execute(TRIGGER_CATEGORY_AFTER_DELETE)
    op.execute(TRIGGER_CATEGORY_AFTER_UPDATE)
    op.execute(TRIGGER_ALLOCATIONS_GUARD_INSERT)
    op.execute(TRIGGER_ALLOCATIONS_GUARD_UPDATE)


TRIGGERS = [
    "trg_categories_amount_guard",
    "trg_categories_after_insert",
    "trg_categories_after_delete",
    "trg_categories_after_update",
    "trg_allocations_guard_insert",
    "trg_allocations_guard_update",
]


def downgrade() -> None:
    bind = op.get_bind()
    for trig in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {trig}")

    op.drop_table("journal_postings")
    op.drop_table("journal_entries")
    op.drop_index("ix_allocations_budget", table_name="allocations")
    op.drop_index("ix_allocations_item_category", table_name="allocations")
    op.drop_index("ix_allocations_entry", table_name="allocations")
    op.drop_table("allocations")
    op.drop_index("ix_item_project_line_assets_line", table_name="item_project_line_assets")
    op.drop_index("ix_item_project_line_assets_item", table_name="item_project_line_assets")
    op.drop_table("item_project_line_assets")
    op.drop_table("line_assets")

    op.drop_index("ix_entries_item_project", table_name="entries")
    op.drop_column("entries", "item_project_id")

    op.drop_index("ix_categories_path_depth", table_name="categories")
    op.drop_index("ix_categories_parent_id", table_name="categories")
    op.drop_index("ix_categories_item_project_leaf", table_name="categories")
    for column in [
        "updated_at",
        "created_at",
        "path_depth",
        "path_names",
        "path_ids",
        "rollup_amount",
        "amount_leaf",
        "is_leaf",
        "description",
        "budget_id",
    ]:
        try:
            op.drop_column("categories", column)
        except sa.exc.OperationalError:
            pass

    op.drop_index("ix_projects_updated_at", table_name="projects")
    op.drop_index("ix_projects_budget_id", table_name="projects")
    for column in ["updated_at", "created_at", "legacy_portfolio_id", "description", "budget_id"]:
        try:
            op.drop_column("projects", column)
        except sa.exc.OperationalError:
            pass

    op.drop_index("ix_funding_sources_updated_at", table_name="funding_sources")
    op.drop_index("ix_funding_sources_is_cost_center", table_name="funding_sources")
    for column in [
        "updated_by",
        "created_by",
        "updated_at",
        "created_at",
        "budget_amount_cache",
        "description",
        "is_cost_center",
        "owner",
    ]:
        try:
            op.drop_column("funding_sources", column)
        except sa.exc.OperationalError:
            pass

    inspector = sa.inspect(bind)
    tag_columns = {col["name"] for col in inspector.get_columns("tags")}
    for column in ["updated_at", "created_at", "is_deprecated", "description", "color"]:
        if column in tag_columns:
            try:
                op.drop_column("tags", column)
            except sa.exc.OperationalError:
                pass
