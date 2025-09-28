"""PR2 journals immutability"""

from __future__ import annotations

from textwrap import dedent

from alembic import op
import sqlalchemy as sa


revision = 'dde21381ed8c'
down_revision = '20240709_01'
branch_labels = None
depends_on = None

CURRENT_TS = sa.text("CURRENT_TIMESTAMP")


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _add_column_if_missing(table: str, column: sa.Column) -> bool:
    if not _has_column(table, column.name):
        op.add_column(table, column)
        return True
    return False



def _has_table(table: str) -> bool:
    conn = op.get_bind()
    rows = conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return rows is not None


def _has_index(table: str, name: str) -> bool:
    conn = op.get_bind()
    rows = op.get_bind().exec_driver_sql(f"PRAGMA index_list({table})").fetchall()
    return any(row[1] == name for row in rows)


def _has_trigger(name: str) -> bool:
    conn = op.get_bind()
    result = conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name = ?",
        (name,),
    ).fetchone()
    return result is not None


def _fk_exists(table: str, ref_table: str, local_cols: list[str], remote_cols: list[str]) -> bool:
    conn = op.get_bind()
    rows = conn.exec_driver_sql(f"PRAGMA foreign_key_list({table})").fetchall()
    by_id: dict[int, dict[str, list[tuple[str, str]]]] = {}
    for row in rows:
        fk_id = row[0]
        info = by_id.setdefault(fk_id, {"table": row[2], "mapping": []})
        info["mapping"].append((row[3], row[4]))
    target = sorted(zip(local_cols, remote_cols), key=lambda pair: pair[0])
    for info in by_id.values():
        if info["table"] != ref_table:
            continue
        mapping = sorted(info["mapping"], key=lambda pair: pair[0])
        if mapping == target:
            return True
    return False


def _ensure_journal_tables():
    if _has_table('journal_entries'):
        required_cols = {'id', 'kind', 'posted_at', 'note', 'created_by', 'created_at'}
        existing = {row[1] for row in op.get_bind().exec_driver_sql("PRAGMA table_info(journal_entries)").fetchall()}
        if not required_cols.issubset(existing):
            op.drop_table('journal_entries')
    if not _has_table('journal_entries'):
        op.create_table(
            'journal_entries',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('kind', sa.String(length=16), nullable=False),
            sa.Column('posted_at', sa.DateTime(), nullable=False, server_default=CURRENT_TS),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('created_by', sa.String(length=100), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=CURRENT_TS),
            sa.CheckConstraint("kind IN ('REALLOC','ADJUST','CORRECTION')", name='ck_journal_kind')
        )
    else:
        added_posted = _add_column_if_missing('journal_entries', sa.Column('posted_at', sa.DateTime(), nullable=True))
        added_kind = _add_column_if_missing('journal_entries', sa.Column('kind', sa.String(length=16), nullable=True))
        added_note = _add_column_if_missing('journal_entries', sa.Column('note', sa.Text(), nullable=True))
        added_created_by = _add_column_if_missing('journal_entries', sa.Column('created_by', sa.String(length=100), nullable=True))
        added_created_at = _add_column_if_missing('journal_entries', sa.Column('created_at', sa.DateTime(), nullable=True))
        if any((added_posted, added_kind, added_created_at, added_note, added_created_by)):
            op.execute(sa.text("""
                UPDATE journal_entries
                SET posted_at = COALESCE(posted_at, CURRENT_TIMESTAMP),
                    kind = COALESCE(kind, 'REALLOC'),
                    note = COALESCE(note, ''),
                    created_by = COALESCE(created_by, 'system'),
                    created_at = COALESCE(created_at, CURRENT_TIMESTAMP)
            """))
        with op.batch_alter_table('journal_entries') as batch:
            batch.alter_column('posted_at', existing_type=sa.DateTime(), nullable=False)
            batch.alter_column('kind', existing_type=sa.String(length=16), nullable=False)
            batch.alter_column('created_at', existing_type=sa.DateTime(), nullable=False)
    if not _has_index('journal_entries', 'ix_journal_entries_posted_at'):
        op.create_index('ix_journal_entries_posted_at', 'journal_entries', ['posted_at'])
    if not _has_index('journal_entries', 'ix_journal_entries_kind_posted'):
        op.create_index('ix_journal_entries_kind_posted', 'journal_entries', ['kind', 'posted_at'])

    if _has_table('journal_postings'):
        required_cols = {'id', 'journal_id', 'allocation_id', 'budget_id', 'item_project_id', 'category_id', 'amount', 'currency', 'created_at'}
        existing = {row[1] for row in op.get_bind().exec_driver_sql("PRAGMA table_info(journal_postings)").fetchall()}
        if not required_cols.issubset(existing):
            op.drop_table('journal_postings')
    if not _has_table('journal_postings'):
        op.create_table(
            'journal_postings',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('journal_id', sa.Integer(), nullable=False),
            sa.Column('allocation_id', sa.Integer(), nullable=True),
            sa.Column('budget_id', sa.Integer(), nullable=True),
            sa.Column('item_project_id', sa.Integer(), nullable=True),
            sa.Column('category_id', sa.Integer(), nullable=True),
            sa.Column('amount', sa.Numeric(18, 2), nullable=False),
            sa.Column('currency', sa.String(length=10), nullable=False, server_default=sa.text("'USD'")),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=CURRENT_TS),
            sa.ForeignKeyConstraint(['journal_id'], ['journal_entries.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['allocation_id'], ['allocations.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['budget_id'], ['funding_sources.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['item_project_id'], ['projects.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='CASCADE'),
            sa.CheckConstraint(
                "(allocation_id IS NOT NULL AND budget_id IS NULL AND item_project_id IS NULL AND category_id IS NULL)"
                " OR (allocation_id IS NULL AND budget_id IS NOT NULL AND item_project_id IS NOT NULL AND category_id IS NOT NULL)",
                name='ck_journal_postings_target'
            )
        )
    else:
        added_currency = _add_column_if_missing('journal_postings', sa.Column('currency', sa.String(length=10), nullable=True, server_default=sa.text("'USD'")))
        added_created_at = _add_column_if_missing('journal_postings', sa.Column('created_at', sa.DateTime(), nullable=True))
        if added_currency:
            op.execute(sa.text("UPDATE journal_postings SET currency = COALESCE(currency, 'USD')"))
        if added_created_at:
            op.execute(sa.text("UPDATE journal_postings SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP)"))
        with op.batch_alter_table('journal_postings') as batch:
            batch.alter_column('currency', existing_type=sa.String(length=10), nullable=False, server_default=sa.text("'USD'"))
            batch.alter_column('created_at', existing_type=sa.DateTime(), nullable=False)
    if not _has_index('journal_postings', 'ix_journal_postings_journal_id'):
        op.create_index('ix_journal_postings_journal_id', 'journal_postings', ['journal_id'])
    if not _has_index('journal_postings', 'ix_journal_postings_allocation_id'):
        op.create_index('ix_journal_postings_allocation_id', 'journal_postings', ['allocation_id'])
    if not _has_index('journal_postings', 'ix_journal_postings_target_triplet'):
        op.create_index('ix_journal_postings_target_triplet', 'journal_postings', ['budget_id', 'item_project_id', 'category_id'])



ENTRY_UPDATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS trg_entries_append_only_update
BEFORE UPDATE ON entries
BEGIN
    SELECT RAISE(ABORT, 'entries are append-only; use journals');
END;
"""

ENTRY_DELETE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS trg_entries_append_only_delete
BEFORE DELETE ON entries
BEGIN
    SELECT RAISE(ABORT, 'entries are append-only; use journals');
END;
"""

ALLOC_UPDATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS trg_allocations_append_only_update
BEFORE UPDATE ON allocations
BEGIN
    SELECT RAISE(ABORT, 'allocations are append-only; use journals');
END;
"""

ALLOC_DELETE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS trg_allocations_append_only_delete
BEFORE DELETE ON allocations
BEGIN
    SELECT RAISE(ABORT, 'allocations are append-only; use journals');
END;
"""

TARGET_GUARD_INSERT = """
CREATE TRIGGER IF NOT EXISTS trg_journal_postings_target_bi
BEFORE INSERT ON journal_postings
BEGIN
    SELECT CASE
        WHEN NEW.allocation_id IS NOT NULL AND (NEW.budget_id IS NOT NULL OR NEW.item_project_id IS NOT NULL OR NEW.category_id IS NOT NULL)
            THEN RAISE(ABORT, 'journal postings must target either allocation or category triplet')
        WHEN NEW.allocation_id IS NULL AND (NEW.budget_id IS NULL OR NEW.item_project_id IS NULL OR NEW.category_id IS NULL)
            THEN RAISE(ABORT, 'journal postings must target either allocation or category triplet')
    END;
END;
"""

TARGET_GUARD_UPDATE = """
CREATE TRIGGER IF NOT EXISTS trg_journal_postings_target_bu
BEFORE UPDATE ON journal_postings
BEGIN
    SELECT CASE
        WHEN NEW.allocation_id IS NOT NULL AND (NEW.budget_id IS NOT NULL OR NEW.item_project_id IS NOT NULL OR NEW.category_id IS NOT NULL)
            THEN RAISE(ABORT, 'journal postings must target either allocation or category triplet')
        WHEN NEW.allocation_id IS NULL AND (NEW.budget_id IS NULL OR NEW.item_project_id IS NULL OR NEW.category_id IS NULL)
            THEN RAISE(ABORT, 'journal postings must target either allocation or category triplet')
    END;
END;
"""

ALLOCATIONS_EFFECTIVE_VIEW = dedent(
    """
    CREATE VIEW IF NOT EXISTS allocations_effective AS
    SELECT
        a.id,
        a.entry_id,
        a.item_project_id,
        a.category_id,
        a.budget_id,
        a.amount,
        a.currency,
        a.posted_at,
        a.created_at,
        a.updated_at,
        COALESCE((SELECT SUM(jp.amount) FROM journal_postings jp WHERE jp.allocation_id = a.id), 0) AS adjustment_delta,
        a.amount + COALESCE((SELECT SUM(jp2.amount) FROM journal_postings jp2 WHERE jp2.allocation_id = a.id), 0) AS effective_amount
    FROM allocations a;
    """
)

CATEGORY_ADJUSTMENTS_VIEW = dedent(
    """
    CREATE VIEW IF NOT EXISTS category_adjustments AS
    SELECT
        jp.id AS posting_id,
        jp.journal_id,
        je.kind,
        je.posted_at,
        jp.budget_id,
        jp.item_project_id,
        jp.category_id,
        jp.amount,
        jp.currency,
        jp.created_at
    FROM journal_postings jp
    JOIN journal_entries je ON je.id = jp.journal_id
    WHERE jp.allocation_id IS NULL;
    """
)


TRIGGERS = [
    ('trg_entries_append_only_update', ENTRY_UPDATE_TRIGGER),
    ('trg_entries_append_only_delete', ENTRY_DELETE_TRIGGER),
    ('trg_allocations_append_only_update', ALLOC_UPDATE_TRIGGER),
    ('trg_allocations_append_only_delete', ALLOC_DELETE_TRIGGER),
    ('trg_journal_postings_target_bi', TARGET_GUARD_INSERT),
    ('trg_journal_postings_target_bu', TARGET_GUARD_UPDATE),
]


VIEWS = [
    ('allocations_effective', ALLOCATIONS_EFFECTIVE_VIEW),
    ('category_adjustments', CATEGORY_ADJUSTMENTS_VIEW),
]


def upgrade() -> None:
    for name in ['trg_journal_postings_balance_ai', 'trg_journal_postings_balance_au', 'trg_journal_postings_balance_ad']:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    _ensure_journal_tables()

    for name, sql in TRIGGERS:
        if not _has_trigger(name):
            op.execute(sql)

    for name, sql in VIEWS:
        op.execute(sql)


def downgrade() -> None:
    for name, _ in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {name}")

    for name, _ in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    if _has_index('journal_postings', 'ix_journal_postings_target_triplet'):
        op.drop_index('ix_journal_postings_target_triplet', table_name='journal_postings')
    if _has_index('journal_postings', 'ix_journal_postings_allocation_id'):
        op.drop_index('ix_journal_postings_allocation_id', table_name='journal_postings')
    if _has_index('journal_postings', 'ix_journal_postings_journal_id'):
        op.drop_index('ix_journal_postings_journal_id', table_name='journal_postings')
    if _has_table('journal_postings'):
        op.drop_table('journal_postings')

    if _has_index('journal_entries', 'ix_journal_entries_kind_posted'):
        op.drop_index('ix_journal_entries_kind_posted', table_name='journal_entries')
    if _has_index('journal_entries', 'ix_journal_entries_posted_at'):
        op.drop_index('ix_journal_entries_posted_at', table_name='journal_entries')
    if _has_table('journal_entries'):
        op.drop_table('journal_entries')
