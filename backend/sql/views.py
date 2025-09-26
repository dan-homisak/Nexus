"""Logical SQL views for reporting surfaces.

Each view is defined as a multi-line SQL string that can be applied by the
initialisation scripts or via Alembic migrations. The views intentionally stay
read-only; existing legacy endpoints can SELECT from them while we build out the
new UI.
"""
from __future__ import annotations

from textwrap import dedent
import threading
import weakref

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

VIEW_DEFINITIONS = {
    "v_budget_commit_actual": dedent(
        """
        CREATE VIEW IF NOT EXISTS v_budget_commit_actual AS
        SELECT
            fs.id AS funding_source_id,
            t.project_id,
            t.category_id,
            COALESCE(t.currency, 'USD') AS currency,
            SUM(CASE WHEN t.state = 'FORECAST' THEN t.amount_txn ELSE 0 END) AS forecast_amount,
            SUM(CASE WHEN t.state = 'COMMITMENT' THEN t.amount_txn ELSE 0 END) AS commitment_amount,
            SUM(CASE WHEN t.state = 'ACCRUAL' THEN t.amount_txn ELSE 0 END) AS accrual_amount,
            SUM(CASE WHEN t.state = 'CASH' THEN t.amount_txn ELSE 0 END) AS cash_amount,
            SUM(CASE WHEN t.state = 'FORECAST' THEN t.amount_usd ELSE 0 END) AS forecast_amount_usd,
            SUM(CASE WHEN t.state = 'COMMITMENT' THEN t.amount_usd ELSE 0 END) AS commitment_amount_usd,
            SUM(CASE WHEN t.state = 'ACCRUAL' THEN t.amount_usd ELSE 0 END) AS accrual_amount_usd,
            SUM(CASE WHEN t.state = 'CASH' THEN t.amount_usd ELSE 0 END) AS cash_amount_usd
        FROM transactions t
        JOIN funding_sources fs ON fs.id = t.funding_source_id
        LEFT JOIN transactions reversal ON reversal.reverses_transaction_id = t.id
        WHERE reversal.id IS NULL
        GROUP BY fs.id, t.project_id, t.category_id, t.currency
        """
    ),
    "v_open_commitments": dedent(
        """
        CREATE VIEW IF NOT EXISTS v_open_commitments AS
        SELECT
            po.id AS purchase_order_id,
            po.po_number,
            po.funding_source_id,
            po.project_id,
            po.vendor_id,
            po.currency,
            po.total_amount,
            po.amount_usd,
            SUM(COALESCE(pl.amount, 0)) AS line_amount,
            SUM(COALESCE(il.amount, 0)) AS invoiced_amount,
            SUM(COALESCE(pl.amount, 0)) - SUM(COALESCE(il.amount, 0)) AS open_amount
        FROM purchase_orders po
        LEFT JOIN po_lines pl ON pl.purchase_order_id = po.id
        LEFT JOIN invoice_lines il ON il.po_line_id = pl.id
        GROUP BY po.id
        HAVING open_amount > 0
        """
    ),
    "v_vendor_spend_aging": dedent(
        """
        CREATE VIEW IF NOT EXISTS v_vendor_spend_aging AS
        SELECT
            t.vendor_id,
            t.currency,
            SUM(CASE WHEN julianday('now') - julianday(t.txn_date) <= 30 THEN t.amount_usd ELSE 0 END) AS bucket_0_30,
            SUM(CASE WHEN julianday('now') - julianday(t.txn_date) BETWEEN 31 AND 60 THEN t.amount_usd ELSE 0 END) AS bucket_31_60,
            SUM(CASE WHEN julianday('now') - julianday(t.txn_date) BETWEEN 61 AND 90 THEN t.amount_usd ELSE 0 END) AS bucket_61_90,
            SUM(CASE WHEN julianday('now') - julianday(t.txn_date) > 90 THEN t.amount_usd ELSE 0 END) AS bucket_90_plus
        FROM transactions t
        WHERE t.state IN ('ACCRUAL', 'CASH')
        GROUP BY t.vendor_id, t.currency
        """
    ),
    "v_open_items": dedent(
        """
        CREATE VIEW IF NOT EXISTS v_open_items AS
        SELECT
            po.id AS purchase_order_id,
            po.po_number,
            po.funding_source_id,
            po.project_id,
            po.vendor_id,
            mi.id AS milestone_instance_id,
            mi.status,
            mi.planned_date,
            mi.actual_date,
            CASE WHEN mi.actual_date IS NULL AND date(mi.planned_date) < date('now') THEN 1 ELSE 0 END AS is_late
        FROM purchase_orders po
        LEFT JOIN po_lines pl ON pl.purchase_order_id = po.id
        LEFT JOIN fulfillment_lots fl ON fl.po_line_id = pl.id
        LEFT JOIN milestone_instances mi ON mi.fulfillment_lot_id = fl.id
        WHERE mi.id IS NULL OR mi.actual_date IS NULL
        """
    ),
    "v_future_plan": dedent(
        """
        CREATE VIEW IF NOT EXISTS v_future_plan AS
        SELECT
            fs.id AS funding_source_id,
            t.project_id,
            t.category_id,
            t.txn_date,
            t.currency,
            t.state,
            t.amount_txn,
            t.amount_usd
        FROM transactions t
        JOIN funding_sources fs ON fs.id = t.funding_source_id
        WHERE t.state IN ('FORECAST', 'COMMITMENT')
        UNION ALL
        SELECT
            fs.id,
            po.project_id,
            pl.category_id,
            COALESCE(ps.due_date, DATE('now', '+60 day')) AS projected_date,
            po.currency,
            'FORECAST' AS state,
            COALESCE(ps.amount, pl.amount * COALESCE(ps.percent, 1)),
            COALESCE(ps.amount, pl.amount * COALESCE(ps.percent, 1)) * po.fx_rate_to_usd
        FROM purchase_orders po
        JOIN funding_sources fs ON fs.id = po.funding_source_id
        JOIN po_lines pl ON pl.purchase_order_id = po.id
        LEFT JOIN payment_schedules ps ON ps.purchase_order_id = po.id
        """
    ),
    "v_to_car_closure": dedent(
        """
        CREATE VIEW IF NOT EXISTS v_to_car_closure AS
        SELECT
            fs.id AS funding_source_id,
            fs.closure_date,
            SUM(t.amount_usd) AS burn_down_usd,
            fs.is_temporary
        FROM funding_sources fs
        LEFT JOIN transactions t ON t.funding_source_id = fs.id
        GROUP BY fs.id
        """
    ),
}


_VIEW_APPLY_LOCK = threading.Lock()
_APPLIED_ENGINES: "weakref.WeakSet[Engine]" = weakref.WeakSet()


def ensure_views(bind) -> None:
    """Apply views once per engine to avoid dropping them mid-request."""

    engine: Engine
    if isinstance(bind, Session):
        engine = bind.bind  # type: ignore[assignment]
        if engine is None:
            raise RuntimeError("Cannot ensure views without a bound engine")
    elif isinstance(bind, Connection):
        engine = bind.engine
    elif isinstance(bind, Engine):
        engine = bind
    else:
        engine = bind

    # When tests use raw sqlite3 connection, skip caching and just apply.
    if not isinstance(engine, Engine):
        apply_views(bind)
        return

    if engine in _APPLIED_ENGINES:
        return

    with _VIEW_APPLY_LOCK:
        if engine in _APPLIED_ENGINES:
            return
        apply_views(engine)
        _APPLIED_ENGINES.add(engine)


def apply_views(bind) -> None:
    """Create or replace the SQL views in a running database connection."""
    if isinstance(bind, Session):
        connection = bind.connection()
        cursor = connection.connection.cursor()
        close_raw = False
    elif isinstance(bind, Engine):
        connection = bind.connect()
        cursor = connection.connection.cursor()
        close_raw = True
    elif isinstance(bind, Connection):
        connection = bind
        cursor = connection.connection.cursor()
        close_raw = False
    else:
        connection = bind
        cursor = connection.cursor()
        close_raw = False
    try:
        for name, sql in VIEW_DEFINITIONS.items():
            cursor.execute(f"DROP VIEW IF EXISTS {name}")
            cursor.execute(sql)
    finally:
        cursor.close()
        if close_raw:
            connection.close()
